"""Minimal disassembler for PS4 (AMD GCN gen 2 / gfx7 "Sea Islands", Liverpool) shader binaries.

usage: py tools/gcn_dis.py <shader.gcn.bin> [...]   -> prints the listing and writes <shader>.s next to it

Written because the Windows LLVM build has no AMDGPU target. Covers the encodings pixel shaders use (SOP*, SMRD,
VOP1/2/3/C, VINTRP, MIMG, MUBUF/MTBUF, DS, EXP); opcode names follow AMD's "Sea Islands Series Instruction Set
Architecture" reference. Unknown opcodes print as op<N> so nothing is silently mis-named.
"""

import os
import struct
import sys

SOP2 = {
    0: "s_add_u32",
    1: "s_sub_u32",
    2: "s_add_i32",
    3: "s_sub_i32",
    4: "s_addc_u32",
    5: "s_subb_u32",
    6: "s_min_i32",
    7: "s_min_u32",
    8: "s_max_i32",
    9: "s_max_u32",
    10: "s_cselect_b32",
    11: "s_cselect_b64",
    14: "s_and_b32",
    15: "s_and_b64",
    16: "s_or_b32",
    17: "s_or_b64",
    18: "s_xor_b32",
    19: "s_xor_b64",
    20: "s_andn2_b32",
    21: "s_andn2_b64",
    22: "s_orn2_b32",
    23: "s_orn2_b64",
    24: "s_nand_b32",
    25: "s_nand_b64",
    26: "s_nor_b32",
    27: "s_nor_b64",
    28: "s_xnor_b32",
    29: "s_xnor_b64",
    30: "s_lshl_b32",
    31: "s_lshl_b64",
    32: "s_lshr_b32",
    33: "s_lshr_b64",
    34: "s_ashr_i32",
    35: "s_ashr_i64",
    36: "s_bfm_b32",
    37: "s_bfm_b64",
    38: "s_mul_i32",
    39: "s_bfe_u32",
    40: "s_bfe_i32",
    41: "s_bfe_u64",
    42: "s_bfe_i64",
    44: "s_absdiff_i32",
}
SOPK = {
    0: "s_movk_i32",
    2: "s_cmovk_i32",
    3: "s_cmpk_eq_i32",
    4: "s_cmpk_lg_i32",
    5: "s_cmpk_gt_i32",
    6: "s_cmpk_ge_i32",
    7: "s_cmpk_lt_i32",
    8: "s_cmpk_le_i32",
    15: "s_addk_i32",
    16: "s_mulk_i32",
    19: "s_getreg_b32",
    20: "s_setreg_b32",
}
SOP1 = {
    3: "s_mov_b32",
    4: "s_mov_b64",
    5: "s_cmov_b32",
    6: "s_cmov_b64",
    7: "s_not_b32",
    8: "s_not_b64",
    9: "s_wqm_b32",
    10: "s_wqm_b64",
    11: "s_brev_b32",
    12: "s_brev_b64",
    13: "s_bcnt0_i32_b32",
    15: "s_bcnt1_i32_b32",
    17: "s_ff0_i32_b32",
    19: "s_ff1_i32_b32",
    21: "s_flbit_i32_b32",
    25: "s_sext_i32_i8",
    26: "s_sext_i32_i16",
    32: "s_getpc_b64",
    33: "s_setpc_b64",
    34: "s_swappc_b64",
    36: "s_and_saveexec_b64",
    37: "s_or_saveexec_b64",
    38: "s_xor_saveexec_b64",
    39: "s_andn2_saveexec_b64",
    40: "s_orn2_saveexec_b64",
    41: "s_nand_saveexec_b64",
    42: "s_nor_saveexec_b64",
    43: "s_xnor_saveexec_b64",
    44: "s_quadmask_b32",
    45: "s_quadmask_b64",
    46: "s_movrels_b32",
    47: "s_movrels_b64",
    48: "s_movreld_b32",
    49: "s_movreld_b64",
    52: "s_abs_i32",
}
SOPC = {
    0: "s_cmp_eq_i32",
    1: "s_cmp_lg_i32",
    2: "s_cmp_gt_i32",
    3: "s_cmp_ge_i32",
    4: "s_cmp_lt_i32",
    5: "s_cmp_le_i32",
    6: "s_cmp_eq_u32",
    7: "s_cmp_lg_u32",
    8: "s_cmp_gt_u32",
    9: "s_cmp_ge_u32",
    10: "s_cmp_lt_u32",
    11: "s_cmp_le_u32",
    12: "s_bitcmp0_b32",
    13: "s_bitcmp1_b32",
}
SOPP = {
    0: "s_nop",
    1: "s_endpgm",
    2: "s_branch",
    4: "s_cbranch_scc0",
    5: "s_cbranch_scc1",
    6: "s_cbranch_vccz",
    7: "s_cbranch_vccnz",
    8: "s_cbranch_execz",
    9: "s_cbranch_execnz",
    10: "s_barrier",
    12: "s_waitcnt",
    13: "s_sethalt",
    14: "s_sleep",
    15: "s_setprio",
    16: "s_sendmsg",
    19: "s_trap",
    20: "s_icache_inv",
    21: "s_incperflevel",
    22: "s_decperflevel",
    23: "s_ttracedata",
}
SMRD = {
    0: "s_load_dword",
    1: "s_load_dwordx2",
    2: "s_load_dwordx4",
    3: "s_load_dwordx8",
    4: "s_load_dwordx16",
    8: "s_buffer_load_dword",
    9: "s_buffer_load_dwordx2",
    10: "s_buffer_load_dwordx4",
    11: "s_buffer_load_dwordx8",
    12: "s_buffer_load_dwordx16",
    30: "s_memtime",
    31: "s_dcache_inv",
}
VOP2 = [
    "v_cndmask_b32",
    "v_readlane_b32",
    "v_writelane_b32",
    "v_add_f32",
    "v_sub_f32",
    "v_subrev_f32",
    "v_mac_legacy_f32",
    "v_mul_legacy_f32",
    "v_mul_f32",
    "v_mul_i32_i24",
    "v_mul_hi_i32_i24",
    "v_mul_u32_u24",
    "v_mul_hi_u32_u24",
    "v_min_legacy_f32",
    "v_max_legacy_f32",
    "v_min_f32",
    "v_max_f32",
    "v_min_i32",
    "v_max_i32",
    "v_min_u32",
    "v_max_u32",
    "v_lshr_b32",
    "v_lshrrev_b32",
    "v_ashr_i32",
    "v_ashrrev_i32",
    "v_lshl_b32",
    "v_lshlrev_b32",
    "v_and_b32",
    "v_or_b32",
    "v_xor_b32",
    "v_bfm_b32",
    "v_mac_f32",
    "v_madmk_f32",
    "v_madak_f32",
    "v_bcnt_u32_b32",
    "v_mbcnt_lo_u32_b32",
    "v_mbcnt_hi_u32_b32",
    "v_add_i32",
    "v_sub_i32",
    "v_subrev_i32",
    "v_addc_u32",
    "v_subb_u32",
    "v_subbrev_u32",
    "v_ldexp_f32",
    "v_cvt_pkaccum_u8_f32",
    "v_cvt_pknorm_i16_f32",
    "v_cvt_pknorm_u16_f32",
    "v_cvt_pkrtz_f16_f32",
    "v_cvt_pk_u16_u32",
    "v_cvt_pk_i16_i32",
]
VOP1 = {
    0: "v_nop",
    1: "v_mov_b32",
    2: "v_readfirstlane_b32",
    5: "v_cvt_f32_i32",
    6: "v_cvt_f32_u32",
    7: "v_cvt_u32_f32",
    8: "v_cvt_i32_f32",
    10: "v_cvt_f16_f32",
    11: "v_cvt_f32_f16",
    12: "v_cvt_rpi_i32_f32",
    13: "v_cvt_flr_i32_f32",
    17: "v_cvt_f32_ubyte0",
    18: "v_cvt_f32_ubyte1",
    19: "v_cvt_f32_ubyte2",
    20: "v_cvt_f32_ubyte3",
    32: "v_fract_f32",
    33: "v_trunc_f32",
    34: "v_ceil_f32",
    35: "v_rndne_f32",
    36: "v_floor_f32",
    37: "v_exp_f32",
    38: "v_log_clamp_f32",
    39: "v_log_f32",
    40: "v_rcp_clamp_f32",
    41: "v_rcp_legacy_f32",
    42: "v_rcp_f32",
    43: "v_rcp_iflag_f32",
    44: "v_rsq_clamp_f32",
    45: "v_rsq_legacy_f32",
    46: "v_rsq_f32",
    51: "v_sqrt_f32",
    53: "v_sin_f32",
    54: "v_cos_f32",
    55: "v_not_b32",
    56: "v_bfrev_b32",
    57: "v_ffbh_u32",
    58: "v_ffbl_b32",
    59: "v_ffbh_i32",
    63: "v_frexp_exp_i32_f32",
    64: "v_frexp_mant_f32",
    66: "v_movreld_b32",
    67: "v_movrels_b32",
    68: "v_movrelsd_b32",
    69: "v_log_legacy_f32",
    70: "v_exp_legacy_f32",
}
VOP3 = {
    320: "v_mad_legacy_f32",
    321: "v_mad_f32",
    322: "v_mad_i32_i24",
    323: "v_mad_u32_u24",
    324: "v_cubeid_f32",
    325: "v_cubesc_f32",
    326: "v_cubetc_f32",
    327: "v_cubema_f32",
    328: "v_bfe_u32",
    329: "v_bfe_i32",
    330: "v_bfi_b32",
    331: "v_fma_f32",
    333: "v_lerp_u8",
    334: "v_alignbit_b32",
    335: "v_alignbyte_b32",
    336: "v_mullit_f32",
    337: "v_min3_f32",
    338: "v_min3_i32",
    339: "v_min3_u32",
    340: "v_max3_f32",
    341: "v_max3_i32",
    342: "v_max3_u32",
    343: "v_med3_f32",
    344: "v_med3_i32",
    345: "v_med3_u32",
    346: "v_sad_u8",
    350: "v_cvt_pk_u8_f32",
    351: "v_div_fixup_f32",
    361: "v_mul_lo_u32",
    362: "v_mul_hi_u32",
    363: "v_mul_lo_i32",
    364: "v_mul_hi_i32",
    365: "v_div_scale_f32",
    367: "v_div_fmas_f32",
}
_CMPF = ["f", "lt", "eq", "le", "gt", "lg", "ge", "o", "u", "nge", "nlg", "ngt", "nle", "neq", "nlt", "tru"]
_CMPI = ["f", "lt", "eq", "le", "gt", "ne", "ge", "t"]


def vopc_name(op):
    if op < 128:
        grp, c = divmod(op, 16)
        kind = {
            0: "v_cmp_%s_f32",
            1: "v_cmpx_%s_f32",
            2: "v_cmp_%s_f64",
            3: "v_cmpx_%s_f64",
            4: "v_cmps_%s_f32",
            5: "v_cmpsx_%s_f32",
            6: "v_cmps_%s_f64",
            7: "v_cmpsx_%s_f64",
        }[grp]
        return kind % _CMPF[c]
    base, c = divmod(op, 8)
    if c == 0 and op in (136, 152, 168, 184):
        pass
    if op == 136:
        return "v_cmp_class_f32"
    if op == 152:
        return "v_cmpx_class_f32"
    t = {
        16: "v_cmp_%s_i32",
        18: "v_cmpx_%s_i32",
        20: "v_cmp_%s_i64",
        22: "v_cmpx_%s_i64",
        24: "v_cmp_%s_u32",
        26: "v_cmpx_%s_u32",
        28: "v_cmp_%s_u64",
        30: "v_cmpx_%s_u64",
    }.get(base)
    return t % _CMPI[c] if t else f"vopc_op{op}"


MIMG = {
    0: "image_load",
    1: "image_load_mip",
    8: "image_store",
    14: "image_get_resinfo",
    32: "image_sample",
    33: "image_sample_cl",
    34: "image_sample_d",
    35: "image_sample_d_cl",
    36: "image_sample_l",
    37: "image_sample_b",
    38: "image_sample_b_cl",
    39: "image_sample_lz",
    40: "image_sample_c",
    41: "image_sample_c_cl",
    42: "image_sample_c_d",
    44: "image_sample_c_l",
    45: "image_sample_c_b",
    47: "image_sample_c_lz",
    48: "image_sample_o",
    50: "image_sample_d_o",
    52: "image_sample_l_o",
    53: "image_sample_b_o",
    55: "image_sample_lz_o",
    64: "image_gather4",
    71: "image_gather4_lz",
    96: "image_get_lod",
}
MUBUF = {
    0: "buffer_load_format_x",
    1: "buffer_load_format_xy",
    2: "buffer_load_format_xyz",
    3: "buffer_load_format_xyzw",
    12: "buffer_load_dword",
    13: "buffer_load_dwordx2",
    14: "buffer_load_dwordx4",
    15: "buffer_load_dwordx3",
}
INLINE_F = {240: "0.5", 241: "-0.5", 242: "1.0", 243: "-1.0", 244: "2.0", 245: "-2.0", 246: "4.0", 247: "-4.0"}


def sreg(n, w=1):
    if n <= 103:
        return f"s{n}" if w == 1 else f"s[{n}:{n + w - 1}]"
    return {
        106: "vcc_lo" if w == 1 else "vcc",
        107: "vcc_hi",
        124: "m0",
        126: "exec_lo" if w == 1 else "exec",
        127: "exec_hi",
        104: "flat_scr_lo",
        105: "flat_scr_hi",
        108: "tba_lo",
        109: "tba_hi",
        110: "tma_lo",
        111: "tma_hi",
    }.get(n, f"ttmp{n - 112}" if 112 <= n <= 123 else f"sreg{n}")


def src(n, lit, w=1):
    if n < 128:
        return sreg(n, w)
    if n == 128:
        return "0"
    if 129 <= n <= 192:
        return str(n - 128)
    if 193 <= n <= 208:
        return str(192 - n)
    if n in INLINE_F:
        return INLINE_F[n]
    if n == 251:
        return "vccz"
    if n == 252:
        return "execz"
    if n == 253:
        return "scc"
    if n == 254:
        return "lds_direct"
    if n == 255:
        (f,) = struct.unpack("<f", struct.pack("<I", lit))
        return f"0x{lit:08x}({f:.6g})"
    if n >= 256:
        v = n - 256
        return f"v{v}" if w == 1 else f"v[{v}:{v + w - 1}]"
    return f"src{n}"


def vreg(n, w=1):
    return f"v{n}" if w == 1 else f"v[{n}:{n + w - 1}]"


def disasm_bytes(code):
    words = struct.unpack(f"<{len(code) // 4}I", code[: len(code) // 4 * 4])
    out, i = [], 0
    while i < len(words):
        pc, w = i * 4, words[i]
        i += 1
        nxt = words[i] if i < len(words) else 0

        def lit_used(*srcs):
            return any(s == 255 for s in srcs)

        text = None
        if w >> 30 == 0b10 and (w >> 23) & 0x7F not in (0x7D, 0x7E, 0x7F) and w >> 28 != 0b1011:  # SOP2
            op, sd, s1, s0 = (w >> 23) & 0x7F, (w >> 16) & 0x7F, (w >> 8) & 0xFF, w & 0xFF
            lit = nxt if lit_used(s0, s1) else None
            if lit is not None:
                i += 1
            name = SOP2.get(op, f"sop2_op{op}")
            wd = 2 if name.endswith("64") else 1
            text = f"{name} {sreg(sd, wd)}, {src(s0, lit, wd)}, {src(s1, lit, wd)}"
        elif w >> 28 == 0b1011 and (w >> 23) & 0x1F < 0x1D:  # SOPK
            op, sd, imm = (w >> 23) & 0x1F, (w >> 16) & 0x7F, w & 0xFFFF
            text = f"{SOPK.get(op, f'sopk_op{op}')} {sreg(sd)}, 0x{imm:x}"
        elif w >> 23 == 0x17D:  # SOP1
            sd, op, s0 = (w >> 16) & 0x7F, (w >> 8) & 0xFF, w & 0xFF
            lit = nxt if s0 == 255 else None
            if lit is not None:
                i += 1
            name = SOP1.get(op, f"sop1_op{op}")
            wd = 2 if "64" in name else 1
            text = f"{name} {sreg(sd, wd)}, {src(s0, lit, wd)}"
        elif w >> 23 == 0x17E:  # SOPC
            op, s1, s0 = (w >> 16) & 0x7F, (w >> 8) & 0xFF, w & 0xFF
            lit = nxt if lit_used(s0, s1) else None
            if lit is not None:
                i += 1
            text = f"{SOPC.get(op, f'sopc_op{op}')} {src(s0, lit)}, {src(s1, lit)}"
        elif w >> 23 == 0x17F:  # SOPP
            op, imm = (w >> 16) & 0x7F, w & 0xFFFF
            name = SOPP.get(op, f"sopp_op{op}")
            if name == "s_waitcnt":
                text = f"s_waitcnt vmcnt({imm & 0xF}) expcnt({(imm >> 4) & 7}) lgkmcnt({(imm >> 8) & 0x1F})"
            elif "branch" in name:
                off = imm - 0x10000 if imm & 0x8000 else imm
                text = f"{name} 0x{pc + 4 + off * 4:x}"
            else:
                text = f"{name} {imm}" if imm else name
        elif w >> 27 == 0b11000:  # SMRD
            op, sd, sb, imm, off = (w >> 22) & 0x1F, (w >> 15) & 0x7F, (w >> 9) & 0x3F, (w >> 8) & 1, w & 0xFF
            name = SMRD.get(op, f"smrd_op{op}")
            n = {"dwordx2": 2, "dwordx4": 4, "dwordx8": 8, "dwordx16": 16}.get(name.split("_")[-1], 1)
            o = f"0x{off * 4:x}" if imm else sreg(off)
            if not imm and off == 255:
                o = f"0x{nxt:x} (lit)"
                i += 1
            text = f"{name} {sreg(sd, n)}, {sreg(sb * 2, 4 if 'buffer' in name else 2)}, {o}"
        elif w >> 31 == 0 and w >> 25 not in (0x3E, 0x3F):  # VOP2 (VOPC/VOP1 share the top bit)
            op, vd, v1, s0 = (w >> 25) & 0x3F, (w >> 17) & 0xFF, (w >> 9) & 0xFF, w & 0x1FF
            lit = nxt if s0 == 255 or op in (32, 33) else None
            if lit is not None:
                i += 1
            name = VOP2[op] if op < len(VOP2) else f"vop2_op{op}"
            if name == "v_madmk_f32":
                text = f"{name} {vreg(vd)}, {src(s0, lit)}, {src(255, lit)}, {vreg(v1)}"
            elif name == "v_madak_f32":
                text = f"{name} {vreg(vd)}, {src(s0, lit)}, {vreg(v1)}, {src(255, lit)}"
            elif name == "v_cndmask_b32":
                text = f"{name} {vreg(vd)}, {src(s0, lit)}, {vreg(v1)}, vcc"
            else:
                text = f"{name} {vreg(vd)}, {src(s0, lit)}, {vreg(v1)}"
        elif w >> 25 == 0x3F:  # VOP1
            vd, op, s0 = (w >> 17) & 0xFF, (w >> 9) & 0xFF, w & 0x1FF
            lit = nxt if s0 == 255 else None
            if lit is not None:
                i += 1
            text = f"{VOP1.get(op, f'vop1_op{op}')} {vreg(vd)}, {src(s0, lit)}"
        elif w >> 25 == 0x3E:  # VOPC
            op, v1, s0 = (w >> 17) & 0xFF, (w >> 9) & 0xFF, w & 0x1FF
            lit = nxt if s0 == 255 else None
            if lit is not None:
                i += 1
            text = f"{vopc_name(op)} vcc, {src(s0, lit)}, {vreg(v1)}"
        elif w >> 26 == 0b110100:  # VOP3
            w2 = nxt
            i += 1
            op = (w >> 17) & 0x1FF
            vd = w & 0xFF
            s0, s1, s2 = w2 & 0x1FF, (w2 >> 9) & 0x1FF, (w2 >> 18) & 0x1FF
            neg, omod = (w2 >> 29) & 7, (w2 >> 27) & 3
            absm, clamp = (w >> 8) & 7, (w >> 11) & 1
            if op < 256:
                name, nsrc, dst = vopc_name(op), 2, sreg(vd, 2)
            elif op < 320:
                name = VOP2[op - 256] if op - 256 < len(VOP2) else f"vop2_op{op - 256}"
                nsrc, dst = (3 if name == "v_cndmask_b32" else 2), vreg(vd)
                if name in ("v_add_i32", "v_sub_i32", "v_subrev_i32", "v_addc_u32", "v_subb_u32"):
                    dst = f"{vreg(vd)}, {sreg((w >> 8) & 0x7F, 2)}"
                    absm, clamp = 0, 0
            elif op < 384:
                name = VOP3.get(op, f"vop3_op{op}")
                nsrc, dst = 3, vreg(vd)
                if name == "v_div_scale_f32":
                    dst = f"{vreg(vd)}, {sreg((w >> 8) & 0x7F, 2)}"
                    absm, clamp = 0, 0
            else:
                name, nsrc, dst = VOP1.get(op - 384, f"vop1_op{op - 384}"), 1, vreg(vd)
            ops = []
            for k, s in enumerate((s0, s1, s2)[:nsrc]):
                t = src(s, None)
                if absm >> k & 1:
                    t = f"|{t}|"
                if neg >> k & 1:
                    t = f"-{t}"
                ops.append(t)
            mods = (" clamp" if clamp else "") + ({1: " mul:2", 2: " mul:4", 3: " div:2"}.get(omod, ""))
            text = f"{name} {dst}, {', '.join(ops)}{mods}"
        elif w >> 26 == 0b110010:  # VINTRP
            vd, op, attr, ch, vs = (w >> 18) & 0xFF, (w >> 16) & 3, (w >> 10) & 0x3F, (w >> 8) & 3, w & 0xFF
            name = ["v_interp_p1_f32", "v_interp_p2_f32", "v_interp_mov_f32", "?"][op]
            text = f"{name} {vreg(vd)}, {vreg(vs)}, attr{attr}.{'xyzw'[ch]}"
        elif w >> 26 == 0b111100:  # MIMG
            w2 = nxt
            i += 1
            op, dmask = (w >> 18) & 0x7F, (w >> 8) & 0xF
            va, vdat, rs, ss = w2 & 0xFF, (w2 >> 8) & 0xFF, (w2 >> 16) & 0x1F, (w2 >> 21) & 0x1F
            n = bin(dmask).count("1")
            text = (
                f"{MIMG.get(op, f'mimg_op{op}')} {vreg(vdat, n)}, {vreg(va, 4)}, {sreg(rs * 4, 8)}, "
                f"{sreg(ss * 4, 4)} dmask:0x{dmask:x}"
            )
        elif w >> 26 in (0b111000, 0b111010):  # MUBUF / MTBUF
            w2 = nxt
            i += 1
            op = (w >> 18) & 0x7F if w >> 26 == 0b111000 else (w >> 16) & 7
            off = w & 0xFFF
            va, vdat, rs, so = w2 & 0xFF, (w2 >> 8) & 0xFF, (w2 >> 16) & 0x1F, (w2 >> 24) & 0xFF
            name = MUBUF.get(op, f"mubuf_op{op}") if w >> 26 == 0b111000 else f"tbuffer_op{op}"
            text = f"{name} {vreg(vdat, 4)}, {vreg(va)}, {sreg(rs * 4, 4)}, {src(so, None)} offset:{off}"
        elif w >> 26 == 0b110110:  # DS
            i += 1
            op = (w >> 18) & 0xFF
            if op == 53:  # ds_swizzle_b32: lane exchange within the wave (quad perm = derivatives)
                text = f"ds_swizzle_b32 v{nxt >> 24}, v{nxt & 0xFF} offset:0x{w & 0xFFFF:x}"
            else:
                text = f"ds_op{op}"
        elif w >> 26 == 0b111110:  # EXP
            w2 = nxt
            i += 1
            en, tgt, compr, done, vm = w & 0xF, (w >> 4) & 0x3F, (w >> 10) & 1, (w >> 11) & 1, (w >> 12) & 1
            t = (
                f"mrt{tgt}"
                if tgt < 8
                else {8: "mrtz", 9: "null"}.get(tgt, f"pos{tgt - 12}" if 12 <= tgt < 16 else f"param{tgt - 32}")
            )
            regs = [vreg((w2 >> (8 * k)) & 0xFF) if en >> k & 1 else "off" for k in range(4)]
            text = (
                f"exp {t}, {', '.join(regs)}"
                + (" compr" if compr else "")
                + (" done" if done else "")
                + (" vm" if vm else "")
            )
        else:
            text = f".long 0x{w:08x}"
        out.append(f"{pc:04x}: {text}")
        if text == "s_endpgm":
            break
    return out


def disasm(path):
    return "\n".join(disasm_bytes(open(path, "rb").read()))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        s = disasm(p)
        open(os.path.splitext(p)[0].replace(".gcn", "") + ".s", "w").write(s + "\n")
        print(s)
