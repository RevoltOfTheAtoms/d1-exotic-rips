"""Helpers for reading the decrypted 1.33 eboot (x86-64 ELF): VA<->file, rip-relative xrefs, disassembly."""

import os
import struct
import sys

import capstone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import PATCH_ROOT

EBOOT = os.path.join(PATCH_ROOT, "eboot.bin")  # the decrypted 1.33 eboot from the patch dump
b = open(EBOOT, "rb").read()
SEGS = []
(_phoff,) = struct.unpack_from("<Q", b, 0x20)
(_n,) = struct.unpack_from("<H", b, 0x38)
for i in range(_n):
    t, fl, off, va, pa, fs, ms, al = struct.unpack_from("<IIQQQQQQ", b, _phoff + i * 56)
    if t == 1:
        SEGS.append((va, off, fs, ms))
TEXT_VA, TEXT_OFF, TEXT_SZ, _ = SEGS[0]
arr = np.frombuffer(b, np.uint8)


def f2v(o):
    for va, off, fs, _ms in SEGS:
        if off <= o < off + fs:
            return o - off + va


def v2f(v):
    for va, off, fs, _ms in SEGS:
        if va <= v < va + fs:
            return v - va + off


def xrefs(target_va, lo=None, hi=None):
    """file offsets p of 4-byte rip-relative displacements with p+4+d == target (in text-segment VA)"""
    lo = TEXT_OFF if lo is None else lo
    hi = TEXT_OFF + TEXT_SZ if hi is None else hi
    d = np.frombuffer(b[lo : hi - (hi - lo) % 4 if False else hi], np.uint8)
    n = len(d) - 4
    disp = (
        d[:n].astype(np.int64)
        | d[1 : n + 1].astype(np.int64) << 8
        | d[2 : n + 2].astype(np.int64) << 16
        | d[3 : n + 3].astype(np.int64) << 24
    )
    disp = np.where(disp >= 1 << 31, disp - (1 << 32), disp)
    pos_va = np.arange(n, dtype=np.int64) + (lo - TEXT_OFF + TEXT_VA)
    out = []
    for extra in (0, 1, 4):  # instr ends right after disp, or after imm8/imm32
        out += list(np.nonzero(pos_va + 4 + extra + disp == target_va)[0] + lo)
    return sorted(set(out))


md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.detail = False


def dis(va, n=80):
    o = v2f(va)
    out = []
    for ins in md.disasm(b[o : o + n * 15], va):
        out.append(f"{ins.address:08x}: {ins.mnemonic} {ins.op_str}")
        if len(out) >= n:
            break
    return out


def func_start(va, maxback=0x4000):
    """guess function start: scan back for int3/ret padding followed by code"""
    o = v2f(va)
    for k in range(o, o - maxback, -1):
        if b[k - 1] in (0xCC, 0xC3) and b[k - 2] in (0xCC, 0xC3, 0x90) or b[k - 16 : k] == b"\x00" * 16:
            pass
    return None


def func(va, maxn=6000, annotate=True):
    """disassemble from va to first int3/padding after a ret; annotate rip-relative float/vec constants"""
    o = v2f(va)
    out = []
    import re as _re

    for ins in md.disasm(b[o : o + maxn * 15], va):
        s = f"{ins.address:08x}: {ins.mnemonic} {ins.op_str}"
        m = _re.search(r"rip ([+-]) (0x[0-9a-f]+)\]", ins.op_str)
        if m and annotate:
            t = ins.address + ins.size + (int(m.group(2), 16) * (1 if m.group(1) == "+" else -1))
            s += f"   ; ->{t:x}"
            fo = v2f(t)
            if fo is not None and ins.mnemonic.startswith("v") and t < TEXT_VA + TEXT_SZ:
                vals = struct.unpack_from("<4f", b, fo)
                s += "  " + str([round(x, 5) for x in vals])
        out.append(s)
        if ins.mnemonic == "int3" or len(out) >= maxn:
            break
    return out


def cstr(va, n=80):
    o = v2f(va)
    if o is None:
        return None
    z = b.find(b"\0", o, o + n)
    s = b[o : z if z >= 0 else o + n]
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return s.decode()
    return None


def func_strs(va, maxn=4000):
    L = func(va, maxn, annotate=True)
    res = []
    import re as _re

    for l in L:
        m = _re.search(r"->([0-9a-f]+)", l)
        s = cstr(int(m.group(1), 16)) if m else None
        res.append(l + (f'   "{s}"' if s else ""))
    return res


def relocs():
    """PS4 SCE dynamic relocations -> dict offset_va -> addend (RELATIVE only) and list of all"""
    dyn_off = 0x1BE30E0
    tags = {}
    for k in range(0, 0xD70, 16):
        t, v = struct.unpack_from("<qQ", b, dyn_off + k)
        tags.setdefault(t, v)
    dynlib = 0x1A25580
    rela, relasz = tags[0x6100002F], tags[0x61000031]
    out = {}
    for k in range(rela, rela + relasz, 24):
        off, info, add = struct.unpack_from("<QQq", b, dynlib + k)
        if info & 0xFFFFFFFF == 8:
            out[off] = add
    return out


def callers(target):
    """file positions of E8 rel32 calls / E9 jmps to target"""
    d = arr[TEXT_OFF : TEXT_OFF + TEXT_SZ]
    n = len(d) - 5
    rel = (
        d[1 : n + 1].astype(np.int64)
        | d[2 : n + 2].astype(np.int64) << 8
        | d[3 : n + 3].astype(np.int64) << 16
        | d[4 : n + 4].astype(np.int64) << 24
    )
    rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
    va = np.arange(n, dtype=np.int64) + TEXT_VA
    ok = ((d[:n] == 0xE8) | (d[:n] == 0xE9)) & (va + 5 + rel == target)
    return [int(x) + TEXT_VA for x in np.nonzero(ok)[0]]
