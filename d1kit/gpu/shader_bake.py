"""Bake gear atlases with the game's own pixel shaders (run on the CPU by gcn_emu.py).

For every atlas pixel the shader of the part's material runs with: the plate diffuse / normal / gearstack, the dye's
detail diffuse / normal, the material's own textures (environment cube, masks), the material's float4 constants and
the dye values the engine writes into the constant buffer at runtime. The colour it exports (mrt0, the surface
colour in the G-buffer, including its baked environment reflection) becomes the glTF base colour.

Runtime constant-buffer slots, counted from the end of the material's float4 array (same layout in every gear
shader read so far; they are zero placeholders in the material):
  [-1] dye colour (primary or secondary by change-colour index)   [-2] dye specular properties
  [-3] dye detail transform (uv scale/offset)                      [-4] .x detail normal strength, .w dye-mask bias
  [-5] .yzw final colour tint (1)
Assumed view for the reflection: the cube is sampled as its mean colour (view independent bake).
"""

import numpy as np

from d1kit.gpu.gcn_emu import Shader
from d1kit.pkg.tags import entry, read
from d1kit.textures.decode import all_texels, extract
from d1kit.textures.texinfo import texinfo

_shaders, _tex, _cube = {}, {}, {}


def shader(ps_tag):
    if ps_tag not in _shaders:
        _, e = entry(ps_tag)
        _shaders[ps_tag] = Shader(read(e["reference"]))
    return _shaders[ps_tag]


def _srgb(a):
    return a**2.2


def tex_array(tag):
    """(H,W,4) float32, sRGB textures linearised (as the GPU does for num format 9)."""
    if tag not in _tex:
        ti = texinfo(tag)
        img, _ = extract(tag)
        a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
        if ti["numfmt"] == 9:
            a[..., :3] = _srgb(a[..., :3])
        _tex[tag] = a
    return _tex[tag]


def cube_mean(tag):
    if tag not in _cube:
        t = all_texels(tag)
        if t is None:
            t = tex_array(tag)[..., :3].reshape(-1, 3)
            _cube[tag] = np.append(t.mean(0), 1.0).astype(np.float32)
        else:
            _cube[tag] = np.append(_srgb(t).mean(0), 1.0).astype(np.float32)
    return _cube[tag]


def sampler(arr):
    h, w = arr.shape[:2]

    def f(u, v, _w):
        x = (np.floor((u % 1.0) * w).astype(np.int64)) % w
        y = (np.floor((v % 1.0) * h).astype(np.int64)) % h
        return arr[y, x]

    return f


def const_sampler(val):
    def f(u, _v, _w):
        return np.broadcast_to(val, (len(u), 4)).astype(np.float32)

    return f


def dye_block_end(ps_tag):
    """Index of the last slot of the gear shader's runtime dye block (colour), found from the shader itself.

    Every gear shader reads the same 14-slot block; its two loads at a 0x...4 offset are the change-colour bias
    (end - 0x4c) and the final colour multiplier (end - 0x3c). The block is usually the end of the constants, but
    Touch of Malice's 80a787d3 has 3 more slots after it (0x210-0x230), so "the last 5 slots" would miss it."""
    import re

    if ("end", ps_tag) not in _shaders:
        offs = sorted(
            {
                int(m.group(1), 16)
                for _, n, r in shader(ps_tag).ops
                if n.startswith("s_buffer_load_dword")
                for m in [re.search(r"s\[16:19\], (0x[0-9a-f]+)", r)]
                if m
            }
        )
        odd = [o for o in offs if o % 16 == 4]
        _shaders[("end", ps_tag)] = (odd[-1] + 0x3C) // 16 if len(odd) >= 2 and odd[-1] - odd[-2] == 0x10 else None
    return _shaders[("end", ps_tag)]


def runtime_cb(constants, dye, secondary, end=None):
    c = [list(x) for x in constants]
    if len(c) < 6:
        return None
    if end is not None and end < len(c) - 1:
        # dye block ends before the last slot: fill it in place, keep the shader's extra slots after it
        head, tail = c[: end + 1], c[end + 1 :]
        return [f for v in _fill_dye(head, dye, secondary) + tail for f in v]
    return [f for v in _fill_dye(c, dye, secondary) for f in v]


def _fill_dye(c, dye, secondary):
    col = (dye["secondary"] if secondary else dye["primary"])[:3] if dye else [0.5, 0.5, 0.5]
    c[-1] = list(col) + [1.0]
    c[-2] = list(dye["specular"]) if dye else [0.0, 0.0, 1.0, 0.0]
    c[-3] = list(dye["detail_transform"]) if dye else [1.0, 1.0, 0.0, 0.0]
    c[-4] = [dye["detail_normal_strength"][0] if dye else 0.0, 0.0, 0.0, 0.0]
    c[-5] = [c[-5][0], 1.0, 1.0, 1.0]
    return c


def bake_group(mi, dye, secondary, diffuse, normal, gearstack, uv, force_dye=False):
    """Run material mi's pixel shader for one group of pixels.
    diffuse/normal/gearstack: (n,4) float32 samples at those pixels (diffuse linear); uv: (n,2) atlas uv.
    Returns (n,3) linear surface colour, or None if the shader can't be run."""
    ps = mi["shaders"].get("ps")
    cb = runtime_cb(mi["constants"], dye, secondary, dye_block_end(int(ps, 16)) if ps else None)
    if not ps or cb is None:
        return None
    n = len(uv)
    textures = {}
    k = 0
    cube = dict(tag=None, mean=None, on=1.0, lod=None)

    def cube_sampler(mean):
        def f(_u, _v, _w, lod=None):
            if lod is not None:
                cube["lod"] = np.asarray(lod, np.float32) * np.ones(len(_u), np.float32)
            return np.broadcast_to(mean * cube["on"], (len(_u), 4)).astype(np.float32)

        f.wants_lod = True
        return f

    for t in sorted(mi["textures"], key=lambda t: t["slot"]):
        if t.get("kind") == "t32/s7":
            # 16-byte stub, not a texture, and not bound in the shader's table (Touch of Malice ps 80a78119 reads
            # the dye detail at index 2 with two real material textures; lens ps 80a3d10c's cube is its first)
            continue
        tag = int(t["tag"], 16)
        try:
            ti = texinfo(tag)
            if ti["type_name"] == "cube":
                m = cube_mean(tag)
                if cube["tag"] is None:
                    cube.update(tag=tag, mean=m)
                textures[k] = cube_sampler(m)
            else:
                textures[k] = sampler(tex_array(tag))
        except Exception:
            textures[k] = const_sampler(np.array([0.5, 0.5, 0.5, 1.0], np.float32))
        k += 1
    if dye and dye.get("detail_diffuse"):
        try:
            textures[k] = sampler(tex_array(dye["detail_diffuse"]))
        except Exception:
            textures[k] = const_sampler(np.array([0.5**2.2] * 3 + [0.5], np.float32))
    else:
        textures[k] = const_sampler(np.array([0.5**2.2] * 3 + [0.5], np.float32))
    if dye and dye.get("detail_normal"):
        try:
            textures[k + 1] = sampler(tex_array(dye["detail_normal"]))
        except Exception:
            textures[k + 1] = const_sampler(np.array([0.5, 0.5, 1.0, 1.0], np.float32))
    else:
        textures[k + 1] = const_sampler(np.array([0.5, 0.5, 1.0, 1.0], np.float32))
    gs = gearstack.copy()
    if force_dye:
        gs[:, 0] = 1.0
    for j, arr in ((k + 2, diffuse), (k + 3, normal), (k + 4, gs)):
        textures[j] = (lambda a: lambda u, v, w: a)(arr)
    one = np.ones(n, np.float32)
    zero = np.zeros(n, np.float32)
    attrs = {
        0: np.stack([one, zero, zero, one], -1),
        1: np.stack([zero, one, zero, zero], -1),
        2: np.stack([zero, zero, one, zero], -1),
        3: np.stack([uv[:, 0], uv[:, 1], uv[:, 0], uv[:, 1]], -1),
        4: np.stack([zero, zero, zero, one], -1),
    }
    frame = [0.0] * 64
    for o in range(0, 64, 4):
        frame[o + 2] = 1.0  # camera along +z, so view vectors are finite
    out = shader(int(ps, 16)).run(n, cb, frame, textures, attrs)
    m, g = out.get("mrt0"), out.get("mrt1")
    if m is None:
        return None
    rgb = np.nan_to_num(m[:, :3], nan=0.0, posinf=1.0, neginf=0.0)
    # Environment reflection, for the viewer to sample per pixel like the game (by reflection direction, at the
    # shader's own mip level): run again with the cube off; reflection = tint * cube sample.
    env = None
    if cube["tag"] is not None:
        cube["on"] = 0.0
        m0 = shader(int(ps, 16)).run(n, cb, frame, textures, attrs).get("mrt0")
        cube["on"] = 1.0
        if m0 is not None:
            base = np.nan_to_num(m0[:, :3], nan=0.0, posinf=1.0, neginf=0.0)
            tint = np.clip((rgb - base) / np.maximum(cube["mean"][:3], 1e-4), 0.0, None)
            lod = cube["lod"] if cube["lod"] is not None else np.zeros(n, np.float32)
            env = dict(
                base=base, tint=tint.astype(np.float32), lod=np.nan_to_num(lod).astype(np.float32), cube=cube["tag"]
            )
    # mrt1 = normal * (0.375 + 0.125 * gloss) + 0.5, .w = BRDF row parameter; the engine's lights decode them as
    # gloss = clamp(4 * |2 * mrt1.xyz - 1| - 3), row = floor(w * 10.6458) (light shader 80aa9d72)
    if g is not None:
        g = np.nan_to_num(g)
        gloss = np.clip(4 * np.linalg.norm(2 * g[:, :3] - 1, axis=1) - 3, 0, 1)
        brdf = np.stack([np.clip(g[:, 3], 0, 1), gloss], -1).astype(np.float32)
    else:
        brdf = None
    return rgb, brdf, env
