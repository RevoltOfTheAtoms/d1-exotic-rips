"""Run a PS4 (GCN gfx7) gear pixel shader on the CPU, vectorised over N pixels, to get the surface colour it writes.

Used to bake textures with the game's own shader maths instead of hand translations. Executes the listing from
gcn_dis.py: scalar/vector ALU, exec masking (if/else via saveexec), interpolation, image sampling through caller
callbacks, constant-buffer loads, and the colour export (mrt0). Branches are not taken: code runs straight through
with exec masks, which is what the hardware does for divergent if/else.

run(code, n, cb, frame_cb, textures, attrs) -> {"mrt0": (n,4), "mrt1": (n,4)}
  cb        material constant buffer: flat list of floats (the material's float4 array, runtime slots filled)
  frame_cb  per-frame/view constant buffer (camera etc.): flat list of floats, or None for zeros
  textures  {table index: callable(u, v, lod_or_None) -> (n,4) float32}; cube lookups get (sc, tc, face)
  attrs     {attr index: (n,4) float32} interpolated vertex outputs
"""

import re
import struct

import numpy as np

from d1kit.gpu.gcn_dis import disasm_bytes

F32 = np.float32
INLINE = {"0.5": 0.5, "-0.5": -0.5, "1.0": 1.0, "-1.0": -1.0, "2.0": 2.0, "-2.0": -2.0, "4.0": 4.0, "-4.0": -4.0}


def _bits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def _flt(b):
    return struct.unpack("<f", struct.pack("<I", b & 0xFFFFFFFF))[0]


class Shader:
    def __init__(self, code):
        self.ops = []
        for line in disasm_bytes(code):
            pc, text = line.split(": ", 1)
            name, _, rest = text.partition(" ")
            self.ops.append((int(pc, 16), name, rest))

    def run(self, n, cb, frame_cb, textures, attrs, quad_w=None):
        """quad_w: width of the row-major pixel grid the n lanes form (lets ds_swizzle see 2x2 pixel quads);
        None = consecutive groups of 4 lanes are the quads."""
        V = {}
        S = {}
        exec_ = np.ones(n, bool)
        vcc = np.zeros(n, bool)
        masks = {}  # sgpr pair base -> bool array (saved exec / compare results)
        desc = {}  # sgpr base -> ("tex", idx) | ("samp", off) | ("buf", off)
        pk = {}  # vgpr -> (lo, hi) from v_cvt_pkrtz
        out = {}
        buf_offs = []

        def vget(tok):
            neg = absv = False
            tok = tok.strip()
            if tok.startswith("-"):
                neg, tok = True, tok[1:]
            if tok.startswith("|") and tok.endswith("|"):
                absv, tok = True, tok[1:-1]
            if tok.startswith("v") and tok[1:].isdigit():
                x = V.get(int(tok[1:]), np.zeros(n, F32))
            elif tok.startswith("s") and tok[1:].isdigit():
                x = F32(_flt(S.get(int(tok[1:]), 0)))
            elif tok in INLINE:
                x = F32(INLINE[tok])
            elif tok.startswith("0x"):
                x = F32(_flt(int(tok.split("(")[0], 16)))
            elif re.fullmatch(r"-?\d+", tok):
                x = F32(_flt(int(tok) & 0xFFFFFFFF))
            elif tok == "vcc":
                x = vcc
            else:
                raise ValueError(f"operand {tok}")
            if absv:
                x = np.abs(x)
            if neg:
                x = -x
            return x

        def sget(tok):
            tok = tok.strip()
            if tok.startswith("s") and tok[1:].isdigit():
                return S.get(int(tok[1:]), 0)
            if tok.startswith("0x"):
                return int(tok.split("(")[0], 16)
            if tok in INLINE:
                return _bits(INLINE[tok])
            if re.fullmatch(r"-?\d+", tok):
                return int(tok) & 0xFFFFFFFF
            if tok.startswith("s["):
                return S.get(int(tok[2:].split(":")[0]), 0)
            raise ValueError(f"scalar operand {tok}")

        def base(tok):
            return int(re.match(r"[sv]\[?(\d+)", tok.strip()).group(1))

        def vset(d, val, clamp=False, omod=1.0):
            val = np.broadcast_to(np.asarray(val, F32), (n,)).astype(F32)
            if omod != 1.0:
                val = val * F32(omod)
            if clamp:
                val = np.clip(val, 0, 1)
            old = V.get(d, np.zeros(n, F32))
            V[d] = np.where(exec_, val, old).astype(F32)

        def legacy_mul(a, b):
            return np.where((a == 0) | (b == 0), F32(0), a * b)

        with np.errstate(all="ignore"):
            for pc, name, rest in self.ops:
                mods = rest
                clamp = " clamp" in mods
                omod = 2.0 if " mul:2" in mods else 4.0 if " mul:4" in mods else 0.5 if " div:2" in mods else 1.0
                rest = re.sub(r" (clamp|mul:\d|div:\d|dmask:0x[0-9a-f]+|compr|done|vm|offset:\d+)", "", rest)
                args = [a.strip() for a in rest.split(", ")] if rest else []

                if (
                    name in ("s_waitcnt", "s_nop", "s_endpgm", "s_wqm_b64", "s_dcache_inv", "s_setprio", "s_sendmsg")
                    or name.startswith("s_cbranch")
                    or name == "s_branch"
                ):
                    if name == "s_endpgm":
                        break
                    continue
                if name == "s_mov_b32":
                    if args[0] == "m0" or args[0].startswith("vcc") or args[0].startswith("exec"):
                        continue
                    S[base(args[0])] = sget(args[1])
                elif name == "s_mov_b64":
                    if args[0] == "exec":
                        exec_ = masks.get(base(args[1]), np.ones(n, bool)).copy()
                    elif args[1] == "exec":
                        masks[base(args[0])] = exec_.copy()
                    else:
                        b0 = base(args[0])
                        S[b0], S[b0 + 1] = sget(args[1]), 0
                elif name == "s_and_saveexec_b64":
                    src = vcc if args[1] == "vcc" else masks[base(args[1])]
                    masks[base(args[0])] = exec_.copy()
                    exec_ = exec_ & src
                elif name == "s_andn2_b64" and args[0] == "exec":
                    exec_ = masks[base(args[1])] & ~exec_
                elif name == "s_and_b64" and args[0] == "exec" and args[1] == "exec" and args[2] != "vcc":
                    continue  # alpha-test discard (live mask): a bake keeps every texel's colour
                elif name in ("s_andn2_b64", "s_and_b64", "s_or_b64") and args[0] != "exec":

                    def m_(t, vcc=vcc, exec_=exec_):  # used right away: bind this iteration's masks
                        return vcc if t == "vcc" else exec_ if t == "exec" else masks.get(base(t), np.ones(n, bool))

                    a, b = m_(args[1]), m_(args[2])
                    masks[base(args[0])] = {"s_andn2_b64": a & ~b, "s_and_b64": a & b, "s_or_b64": a | b}[name]
                elif name in ("s_and_b64", "s_or_b64") and args[0] == "exec":
                    a = vcc if args[1] == "vcc" else masks.get(base(args[1]), exec_)
                    b = exec_ if args[2] == "exec" else (vcc if args[2] == "vcc" else masks.get(base(args[2]), exec_))
                    exec_ = (a & b) if name == "s_and_b64" else (a | b)
                elif name in ("s_load_dwordx4", "s_load_dwordx8"):
                    off = int(args[2], 16)
                    if args[1] == "s[12:13]":
                        desc[base(args[0])] = ("tex", off // 0x20)
                    elif name == "s_load_dwordx8" and args[1] == "s[2:3]":
                        # effect shaders keep textures in the s[2:3] table (8-dword T#s at 0x00, 0x20, ...), after the
                        # one bound straight in user data (s[4:11]) = the material's first texture
                        desc[base(args[0])] = ("tex", 1 + off // 0x20)
                    else:
                        desc[base(args[0])] = ("ptr", off)
                elif name.startswith("s_buffer_load_dword"):
                    cnt = {
                        "s_buffer_load_dword": 1,
                        "s_buffer_load_dwordx2": 2,
                        "s_buffer_load_dwordx4": 4,
                        "s_buffer_load_dwordx8": 8,
                        "s_buffer_load_dwordx16": 16,
                    }[name]
                    d0, bd, off = base(args[0]), base(args[1]), int(args[2], 16)
                    key = desc.get(bd, ("ptr", -1))[1]
                    if key not in buf_offs:
                        buf_offs.append(key)
                    src = cb if key == min(buf_offs) else (frame_cb or [])
                    for k in range(cnt):
                        i = off // 4 + k
                        S[d0 + k] = _bits(src[i]) if i < len(src) else 0
                elif name == "s_load_dword" or name == "s_load_dwordx2":
                    continue
                elif name.startswith("s_"):
                    if name in ("s_add_u32", "s_add_i32"):
                        S[base(args[0])] = (sget(args[1]) + sget(args[2])) & 0xFFFFFFFF
                    elif name in ("s_mul_i32",):
                        S[base(args[0])] = (sget(args[1]) * sget(args[2])) & 0xFFFFFFFF
                    elif name == "s_lshl_b32":
                        S[base(args[0])] = (sget(args[1]) << (sget(args[2]) & 31)) & 0xFFFFFFFF
                    elif name == "s_movk_i32":
                        S[base(args[0])] = int(args[1], 16)
                    else:
                        raise NotImplementedError(f"{pc:04x} {name} {rest}")
                elif name in ("v_interp_p1_f32", "v_interp_p2_f32", "v_interp_mov_f32"):
                    m = re.match(r"attr(\d+)\.([xyzw])", args[2])
                    a = attrs.get(int(m.group(1)))
                    vset(base(args[0]), a[:, "xyzw".index(m.group(2))] if a is not None else 0.0)
                elif name.startswith("image_"):
                    nd = int(re.search(r"dmask:0x([0-9a-f]+)", mods).group(1), 16)
                    d0, a0, rs = base(args[0]), base(args[1]), base(args[2])
                    # s[4:11] with no load: a T# bound straight in user data = the material's first texture
                    kind = desc.get(rs, ("tex", 0) if rs == 4 else ("tex", -1))
                    if name == "image_get_lod":
                        res = np.zeros((n, 4), F32)
                    else:
                        fn = textures.get(kind[1])
                        c0, c1, c2 = (V.get(a0 + k, np.zeros(n, F32)) for k in range(3))
                        if fn is not None and getattr(fn, "wants_lod", False):  # cube: also pass the 4th coord (lod)
                            res = fn(c0, c1, c2, V.get(a0 + 3) if name == "image_sample_l" else None)
                        else:
                            res = fn(c0, c1, c2) if fn else np.zeros((n, 4), F32)
                    k = 0
                    for ch in range(4):
                        if nd >> ch & 1:
                            vset(d0 + k, res[:, ch])
                            k += 1
                elif name == "ds_swizzle_b32":
                    off = int(re.search(r"offset:0x([0-9a-f]+)", mods).group(1), 16)
                    if not off & 0x8000:
                        raise NotImplementedError(f"{pc:04x} {name} {rest} (bitmask mode)")
                    i = np.arange(n)
                    if quad_w:
                        x, y = i % quad_w, i // quad_w
                        q = (x & 1) + 2 * (y & 1)
                    else:
                        q = i & 3
                    p = (off >> (2 * q)) & 3
                    src_l = (i - (x & 1) - quad_w * (y & 1) + (p & 1) + quad_w * (p >> 1)) if quad_w else (i - q + p)
                    src_l = np.clip(src_l, 0, n - 1)
                    vset(base(args[0]), V.get(base(args[1]), np.zeros(n, F32))[src_l])
                elif name == "exp":
                    tgt = args[0]
                    regs = args[1:5]
                    if "compr" in mods:
                        lo = pk.get(base(regs[0]), (np.zeros(n, F32),) * 2)
                        hi = pk.get(base(regs[1]), (np.zeros(n, F32),) * 2)
                        out[tgt] = np.stack([lo[0], lo[1], hi[0], hi[1]], -1)
                    else:
                        out[tgt] = np.stack(
                            [V.get(base(r), np.zeros(n, F32)) if r != "off" else np.zeros(n, F32) for r in regs], -1
                        )
                elif name == "v_cvt_pkrtz_f16_f32":
                    pk[base(args[0])] = (
                        np.asarray(vget(args[1])).astype(F32) * np.ones(n, F32),
                        np.asarray(vget(args[2])).astype(F32) * np.ones(n, F32),
                    )
                elif name.startswith("v_cmp"):
                    a, b = vget(args[1]), vget(args[2])
                    op = name.split("_")[2]
                    r = {
                        "lt": a < b,
                        "gt": a > b,
                        "le": a <= b,
                        "ge": a >= b,
                        "eq": a == b,
                        "lg": a != b,
                        "neq": ~(a == b),
                        "nlt": ~(a < b),
                        "ngt": ~(a > b),
                        "nle": ~(a <= b),
                        "nge": ~(a >= b),
                        "ne": a != b,
                        "f": np.zeros(n, bool),
                        "tru": np.ones(n, bool),
                    }[op]
                    r = np.broadcast_to(r, (n,)) & exec_
                    if args[0] == "vcc":
                        vcc = r.copy()
                    else:
                        masks[base(args[0])] = r.copy()
                    if name.startswith("v_cmpx"):
                        exec_ = r.copy()
                else:
                    d = base(args[0])
                    src = args[1:]
                    if name in ("v_add_i32", "v_sub_i32", "v_subrev_i32", "v_div_scale_f32") and len(src) > 2:
                        src = src[1:]
                    x = [vget(s) for s in src if s not in ("vcc", "vcc_lo")]
                    if name == "v_mov_b32":
                        r = x[0]
                    elif name == "v_add_f32":
                        r = x[0] + x[1]
                    elif name == "v_sub_f32":
                        r = x[0] - x[1]
                    elif name == "v_subrev_f32":
                        r = x[1] - x[0]
                    elif name == "v_mul_f32":
                        r = x[0] * x[1]
                    elif name == "v_mul_legacy_f32":
                        r = legacy_mul(x[0], x[1])
                    elif name == "v_mac_f32":
                        r = x[0] * x[1] + V.get(d, np.zeros(n, F32))
                    elif name == "v_mac_legacy_f32":
                        r = legacy_mul(x[0], x[1]) + V.get(d, np.zeros(n, F32))
                    elif name in ("v_mad_f32", "v_fma_f32"):
                        r = x[0] * x[1] + x[2]
                    elif name == "v_mad_legacy_f32":
                        r = legacy_mul(x[0], x[1]) + x[2]
                    elif name == "v_madak_f32":
                        r = x[0] * x[1] + x[2]
                    elif name == "v_madmk_f32":
                        r = x[0] * x[1] + x[2]
                    elif name in ("v_max_f32", "v_max_legacy_f32"):
                        r = np.maximum(x[0], x[1])
                    elif name in ("v_min_f32", "v_min_legacy_f32"):
                        r = np.minimum(x[0], x[1])
                    elif name == "v_max3_f32":
                        r = np.maximum(np.maximum(x[0], x[1]), x[2])
                    elif name == "v_min3_f32":
                        r = np.minimum(np.minimum(x[0], x[1]), x[2])
                    elif name == "v_med3_f32":
                        r = np.median(np.stack(np.broadcast_arrays(x[0], x[1], x[2])), 0)
                    elif name in ("v_rcp_f32", "v_rcp_clamp_f32", "v_rcp_legacy_f32", "v_rcp_iflag_f32"):
                        r = F32(1) / x[0]
                        if name != "v_rcp_f32":
                            r = np.clip(r, -3.4e38, 3.4e38)
                    elif name in ("v_rsq_f32", "v_rsq_clamp_f32", "v_rsq_legacy_f32"):
                        r = F32(1) / np.sqrt(x[0])
                        if name != "v_rsq_f32":
                            r = np.clip(r, -3.4e38, 3.4e38)
                    elif name == "v_sqrt_f32":
                        r = np.sqrt(x[0])
                    elif name == "v_exp_f32":
                        r = np.exp2(x[0])
                    elif name in ("v_log_f32", "v_log_clamp_f32"):
                        r = np.log2(x[0])
                    elif name == "v_fract_f32":
                        r = x[0] - np.floor(x[0])
                    elif name in ("v_cvt_i32_f32", "v_cvt_u32_f32"):
                        r = np.trunc(x[0])  # integer value kept as a float (only used for counts/compares here)
                    elif name in ("v_cvt_f32_i32", "v_cvt_f32_u32"):
                        r = x[0]
                    elif name == "v_floor_f32":
                        r = np.floor(x[0])
                    elif name == "v_ceil_f32":
                        r = np.ceil(x[0])
                    elif name == "v_trunc_f32":
                        r = np.trunc(x[0])
                    elif name == "v_cndmask_b32":
                        sel = vcc if len(src) < 3 or src[2] in ("vcc", "vcc_lo") else masks.get(base(src[2]), vcc)
                        r = np.where(sel, x[1], x[0])
                    elif name in ("v_cubema_f32", "v_cubesc_f32", "v_cubetc_f32", "v_cubeid_f32"):
                        r = np.ones(n, F32) if name == "v_cubema_f32" else np.zeros(n, F32)
                    elif name in ("v_sin_f32", "v_cos_f32"):
                        r = (np.sin if name == "v_sin_f32" else np.cos)(x[0] * F32(2 * np.pi))
                    elif name == "v_ldexp_f32":
                        r = x[0] * np.exp2(np.asarray(x[1]).view(np.int32) if isinstance(x[1], np.ndarray) else 0)
                    else:
                        raise NotImplementedError(f"{pc:04x} {name} {rest}")
                    vset(d, r, clamp, omod)
        self.last = dict(V=V, S=S, exec=exec_)  # debug: final register state
        return out
