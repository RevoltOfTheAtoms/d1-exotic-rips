"""PS4 (GNM) texture extraction for D1: detile 1D-thin micro tiles, write DDS, decode to PNG.

Thin micro tile = 8x8 elements (BC blocks or pixels), element order Morton x0 y0 x1 y1 x2 y2; tiles row-major.
"""

import io
import os
import struct
import sys

import numpy as np
from PIL import Image

from d1kit.pkg.tags import read
from d1kit.textures.texinfo import texinfo

BLOCK = {
    "BC1": (4, 8),
    "BC2": (4, 16),
    "BC3": (4, 16),
    "BC4": (4, 8),
    "BC5": (4, 16),
    "BC7": (4, 16),
    "R8G8B8A8": (1, 4),
    "R8": (1, 1),
    "R8G8": (1, 2),
}

_morton = np.zeros(64, dtype=np.int64)
for _i in range(64):
    _x = (_i & 1) | ((_i >> 1) & 2) | ((_i >> 2) & 4)
    _y = ((_i >> 1) & 1) | ((_i >> 2) & 2) | ((_i >> 3) & 4)
    _morton[_i] = _y * 8 + _x  # morton index -> linear index within tile


def detile_1d_thin(data, w_el, h_el, pitch_el, esize):
    """Return linear (h_el, w_el, esize) array from 1D-thin tiled data."""
    tiles_x = (pitch_el + 7) // 8
    tiles_y = (h_el + 7) // 8
    need = tiles_x * tiles_y * 64 * esize
    buf = np.frombuffer(data[:need].ljust(need, b"\0"), dtype=np.uint8).reshape(tiles_y, tiles_x, 64, esize)
    lin = np.empty_like(buf)
    lin[:, :, _morton, :] = buf  # place morton-ordered elements at their linear spot
    img = lin.reshape(tiles_y, tiles_x, 8, 8, esize).transpose(0, 2, 1, 3, 4).reshape(tiles_y * 8, tiles_x * 8, esize)
    return img[:h_el, :w_el]


def dds_bytes(fmt, w, h, payload):
    fourcc = {"BC1": b"DXT1", "BC2": b"DXT3", "BC3": b"DXT5", "BC4": b"ATI1", "BC5": b"ATI2"}.get(fmt)
    if fourcc:
        pf = struct.pack("<II4s5I", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
        flags, pitch = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, len(payload)
    else:
        pf = struct.pack("<II4s5I", 32, 0x41, b"\0\0\0\0", 32, 0xFF, 0xFF00, 0xFF0000, 0xFF000000)
        flags, pitch = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, w * 4
    hdr = (
        struct.pack("<I I I I I I I 11I", 124, flags, h, w, pitch, 0, 1, *([0] * 11))
        + pf
        + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    )
    return b"DDS " + hdr + payload


def extract(tag, out_base=None, layout=None):
    """Decode mip 0 of a texture tag. Returns (PIL.Image, info). Writes .dds/.png when out_base given.

    layout: "linear" for gear plate textures (stored untiled for runtime compositing), otherwise 1D-thin tiled.
    A data size that doesn't match the untiled mip chain is always treated as tiled."""
    info = texinfo(tag)
    fmt = info["fmt_name"]
    if fmt not in BLOCK:
        raise NotImplementedError(f"format {fmt} ({info['fmt']})")
    bdim, esize = BLOCK[fmt]
    w, h, pitch = info["width"], info["height"], info["pitch"]
    faces = 6 if info["type_name"] == "cube" else 1
    data = read(info["data_tag"])
    w_el, h_el, p_el = -(-w // bdim), -(-h // bdim), -(-pitch // bdim)
    # Gear plate textures are stored linear (mip 0 first) even though the T# says 1D-thin. Size can't tell the
    # two apart when dimensions are multiples of 8, so the caller says which it is.
    # mip m is (w >> m) x (h >> m) pixels, rounded up to whole blocks (e.g. 760 px tall: 190, 95, 48, 24, 12 blocks)
    linear_size = (
        sum(-(-max(1, w >> m) // bdim) * -(-max(1, h >> m) // bdim) * esize for m in range(info["last_level"] + 1))
        * faces
    )
    info["layout"] = "linear" if layout == "linear" and len(data) == linear_size else "1dthin"
    if info["layout"] == "linear":
        lin = np.frombuffer(data[: w_el * h_el * esize], dtype=np.uint8).reshape(h_el, w_el, esize)
    else:
        lin = detile_1d_thin(data, w_el, h_el, p_el, esize)  # face 0 / mip 0 only
    if bdim == 4:
        payload = lin.reshape(h_el, w_el, esize).tobytes()
        img = Image.open(io.BytesIO(dds_bytes(fmt, w, h, payload)))
        img.load()
    else:
        arr = lin.reshape(h, w, esize)
        img = Image.fromarray(arr.astype(np.uint8), "RGBA" if esize == 4 else ("L" if esize == 1 else "LA"))
        payload = arr.tobytes()
    if fmt == "BC5":  # two-channel normal: rebuild Z for viewing
        a = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
        x, y = a[..., 0] * 2 - 1, a[..., 1] * 2 - 1
        z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
        img = Image.fromarray((np.stack([x, y, z], -1) * 0.5 + 0.5).clip(0, 1).__mul__(255).astype(np.uint8), "RGB")
    if out_base:
        os.makedirs(os.path.dirname(out_base), exist_ok=True)
        with open(out_base + ".dds", "wb") as f:
            f.write(dds_bytes(fmt, w, h, payload))
        img.save(out_base + ".png")
    info["faces"] = faces
    return img, info


def all_texels(tag):
    """Every texel of a texture's data (all cube faces and mips, tiling ignored): (N,3) sRGB 0..1.
    Only BC1 and R8G8B8A8, the formats gear environment cubes use; None otherwise."""
    ti = texinfo(tag)
    d = np.frombuffer(read(ti["data_tag"]), np.uint8)
    if ti["fmt_name"] == "R8G8B8A8":
        return d[: len(d) // 4 * 4].reshape(-1, 4)[:, :3].astype(np.float32) / 255.0
    if ti["fmt_name"] != "BC1":
        return None
    blk = d[: len(d) // 8 * 8].reshape(-1, 8)
    c0 = blk[:, 0].astype(np.uint32) | blk[:, 1].astype(np.uint32) << 8
    c1 = blk[:, 2].astype(np.uint32) | blk[:, 3].astype(np.uint32) << 8

    def rgb(c):
        return np.stack([(c >> 11 & 31) / 31.0, (c >> 5 & 63) / 63.0, (c & 31) / 31.0], -1).astype(np.float32)

    p0, p1 = rgb(c0), rgb(c1)
    four = (c0 > c1)[:, None]
    pal = np.stack(
        [p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0.0)], 1
    )
    idx = np.unpackbits(blk[:, 4:8], axis=1, bitorder="little").reshape(-1, 16, 2)
    sel = idx[..., 0] + 2 * idx[..., 1]
    return np.take_along_axis(pal, sel[..., None].repeat(3, -1), 1).reshape(-1, 3)


if __name__ == "__main__":
    for a in sys.argv[2:]:
        im, inf = extract(int(a, 16), os.path.join(sys.argv[1], a))
        print(a, inf["fmt_name"], im.size, im.mode)
