"""Minimal Destiny 1 (PS4, little-endian, RoI-style header) Tiger package reader.

Layout follows tiger-pkg src/d1_roi/structs.rs. Read-only on the source packages.
"""

import ctypes
import os
import struct
import sys

BLOCK_SIZE = 0x40000


LINUX_LIB = "liblinoodle3.so"  # linoodle: runs oo2core_3_win64.dll inside a Linux process (from tiger-pkg)


class OodleUnavailable(RuntimeError):
    """Oodle can't be loaded on this system; the message says why."""


def load_oodle_library(dll_path):
    """The legacy Oodle library for this OS, the way tiger-pkg loads it:
    Windows: oo2core_3_win64.dll. Linux: liblinoodle3.so from the same folder, which loads that DLL itself
    (it looks for the DLL in the current folder, so it's loaded from the DLL's folder). Other systems: unsupported."""
    if sys.platform == "win32":
        return ctypes.WinDLL(dll_path)
    if sys.platform.startswith("linux"):
        folder = os.path.dirname(os.path.abspath(dll_path))
        lib = os.path.join(folder, LINUX_LIB)
        if not os.path.isfile(lib):
            raise OodleUnavailable(f"{LINUX_LIB} is missing from {folder} (run setup, or see README: Linux)")
        cwd = os.getcwd()
        os.chdir(folder)
        try:
            return ctypes.CDLL(lib)
        finally:
            os.chdir(cwd)
    raise OodleUnavailable("This project supports Windows and x86-64 Linux only.")


class Oodle:
    def __init__(self, dll_path):
        self.lib = load_oodle_library(dll_path)
        self.fn = self.lib.OodleLZ_Decompress
        self.fn.restype = ctypes.c_int64
        self.fn.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_int,
        ]

    def decompress(self, data, out_size=BLOCK_SIZE):
        out = ctypes.create_string_buffer(BLOCK_SIZE + 0x10000)  # legacy Oodle may overrun rawLen
        n = self.fn(data, len(data), out, out_size, 0, 0, 0, None, 0, None, None, None, 0, 3)
        if n <= 0:
            raise RuntimeError(f"OodleLZ_Decompress failed ({n})")
        return out.raw[:n]


class Package:
    def __init__(self, path, oodle=None, search=None):
        self.path = path
        self.oodle = oodle
        # folders holding this package's other patch files (patch dumps keep _0 on the base disc)
        self.search = search or [os.path.dirname(path)]
        self._files = {}
        self.f = open(path, "rb")
        h = self.f.read(0x140)
        self.version, self.platform, self.pkg_id = struct.unpack_from("<HHH", h, 0)
        self.patch_id, self.language = struct.unpack_from("<HH", h, 0x20)
        self.tool_string = h[0x24:0xA4].rstrip(b"\0").decode("latin-1")
        (self.entry_count, self.entry_off) = struct.unpack_from("<II", h, 0xB4)
        (self.block_count, self.block_off) = struct.unpack_from("<II", h, 0xD0)
        (self.named_count, self.named_off) = struct.unpack_from("<II", h, 0xEC)
        assert self.version == 24, f"unexpected pkg version {self.version}"

        self.f.seek(self.entry_off)
        raw = self.f.read(self.entry_count * 16)
        self.entries = []
        for i in range(self.entry_count):
            ref, thing, binfo = struct.unpack_from("<IIQ", raw, i * 16)
            self.entries.append(
                dict(
                    index=i,
                    reference=ref,
                    type=thing & 0xFFFF,
                    subtype=thing >> 24,
                    block=binfo & 0x3FFF,
                    block_off=((binfo >> 14) & 0x3FFF) << 4,
                    size=(binfo >> 28) & 0x3FFFFFFF,
                )
            )

        self.f.seek(self.block_off)
        raw = self.f.read(self.block_count * 32)
        self.blocks = []
        for i in range(self.block_count):
            off, size, patch, flags = struct.unpack_from("<IIHH", raw, i * 32)
            self.blocks.append(dict(offset=off, size=size, patch=patch, flags=flags))

        self.f.seek(self.named_off)
        raw = self.f.read(self.named_count * 68)
        self.named = []
        for i in range(self.named_count):
            th, cls = struct.unpack_from("<II", raw, i * 68)
            name = raw[i * 68 + 8 : i * 68 + 68].split(b"\0")[0].decode("latin-1")
            self.named.append((th, cls, name))
        self._cache = {}

    def _block(self, i):
        if i in self._cache:
            return self._cache[i]
        b = self.blocks[i]
        if b["patch"] == self.patch_id:
            f = self.f
        else:
            f = self._patch_file(b["patch"])
        f.seek(b["offset"])
        data = f.read(b["size"])
        if b["flags"] & 1:
            try:
                data = self.oodle.decompress(data)
            except RuntimeError:
                # legacy Oodle wants the exact raw size; true for the short final block
                data = self._decompress_short(i, data)
        if len(self._cache) > 8:
            self._cache.clear()
        self._cache[i] = data
        return data

    def _patch_file(self, patch):
        if patch not in self._files:
            name = os.path.basename(self.path)
            name = f"{name[: name.rfind('_')]}_{patch}.pkg"
            path = next((os.path.join(d, name) for d in self.search if os.path.exists(os.path.join(d, name))), None)
            if path is None:
                raise FileNotFoundError(f"{name} not found in {self.search}")
            self._files[patch] = open(path, "rb")
        return self._files[patch]

    def _decompress_short(self, i, data):
        need = 0
        for e in self.entries:
            start = e["block"] * BLOCK_SIZE + e["block_off"]
            end = start + e["size"]
            if start < (i + 1) * BLOCK_SIZE and end > i * BLOCK_SIZE:
                need = max(need, end - i * BLOCK_SIZE)
        # raw length of a short block is padded to the codec's 16 KB quantum
        first = (min(need, BLOCK_SIZE) + 0x3FFF) & ~0x3FFF
        for size in range(max(first, 0x4000), BLOCK_SIZE + 1, 0x4000):
            try:
                return self.oodle.decompress(data, size)
            except RuntimeError:
                continue
        raise RuntimeError(f"block {i}: no raw size found near {need:#x}")

    def read_entry(self, idx):
        e = self.entries[idx]
        out = bytearray()
        blk, off, remaining = e["block"], e["block_off"], e["size"]
        while remaining > 0:
            data = self._block(blk)
            chunk = data[off : off + remaining]
            out += chunk
            remaining -= len(chunk)
            blk, off = blk + 1, 0
        return bytes(out)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--oodle", required=True)
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    p = Package(a.pkg, Oodle(a.oodle))
    print(
        f"pkg {p.pkg_id:04x}_{p.patch_id} platform={p.platform} lang={p.language} "
        f"entries={p.entry_count} blocks={p.block_count} named={p.named_count} [{p.tool_string}]"
    )
    if a.list:
        for e in p.entries:
            print(e)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        ok = fail = 0
        for e in p.entries:
            try:
                d = p.read_entry(e["index"])
                fn = f"{e['index']}_{e['reference']:08x}_t{e['type']}_s{e['subtype']}.bin"
                with open(os.path.join(a.out, fn), "wb") as o:
                    o.write(d)
                ok += 1
            except Exception as ex:
                fail += 1
                print("fail", e["index"], ex, file=sys.stderr)
        print(f"extracted {ok}, failed {fail}")
