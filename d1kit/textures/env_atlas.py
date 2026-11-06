"""Decode a gear environment cube (all 6 faces, every mip the game ships) into one atlas PNG for the viewer.

Layout: mip m is a row of 6 faces (GCN order +X -X +Y -Y +Z -Z), each S>>m pixels square; rows stacked top to
bottom starting with mip 0. Atlas size 6*S x (S + S/2 + ... + 1). Colours stay sRGB as stored (num format 9).
Mip 0 is read from the game data (all 6 faces first, each 1D-thin tiled). The smaller mips that follow use a tiling
not decoded here, so the blur levels are rebuilt from mip 0 by 2x2 averaging in linear light (an approximation of the
game's own pre-filtered mips).

usage: env_atlas.py <cube tag hex> [...]   -> preview/env_<tag>.png
"""

import io
import os
import sys

import numpy as np
from PIL import Image

from d1kit.config import FRONTEND_DIR
from d1kit.pkg.tags import read
from d1kit.textures.decode import BLOCK, dds_bytes, detile_1d_thin
from d1kit.textures.texinfo import texinfo


def cube_faces(tag):
    """[(mip, [6 x (S,S,3) uint8 sRGB])] for every mip level."""
    ti = texinfo(tag)
    assert ti["type_name"] == "cube", ti
    fmt = ti["fmt_name"]
    bdim, esize = BLOCK[fmt]
    data = read(ti["data_tag"])
    s = ti["width"]
    el = -(-s // bdim)
    tiles = -(-el // 8)
    face_bytes = tiles * tiles * 64 * esize
    faces = []
    for f in range(6):
        lin = detile_1d_thin(data[f * face_bytes : (f + 1) * face_bytes], el, el, tiles * 8, esize)
        if bdim == 1:
            img = np.ascontiguousarray(lin.reshape(s, s, esize)[..., :3])
        else:
            im = Image.open(io.BytesIO(dds_bytes(fmt, el * 4, el * 4, np.ascontiguousarray(lin).tobytes())))
            im.load()
            img = np.asarray(im.convert("RGB"))[:s, :s]
        faces.append(img)
    mips = [(0, faces)]
    cur = [(f.astype(np.float32) / 255.0) ** 2.2 for f in faces]
    m = 0
    while cur[0].shape[0] > 1:
        m += 1
        cur = [c.reshape(c.shape[0] // 2, 2, c.shape[1] // 2, 2, 3).mean((1, 3)) for c in cur]
        mips.append((m, [(c ** (1 / 2.2) * 255 + 0.5).astype(np.uint8) for c in cur]))
    return mips


def atlas(tag):
    mips = cube_faces(tag)
    s0 = mips[0][1][0].shape[0]
    h = sum(f[0].shape[0] for _, f in mips)
    out = np.zeros((h, 6 * s0, 3), np.uint8)
    y = 0
    for _, faces in mips:
        s = faces[0].shape[0]
        for f, img in enumerate(faces):
            out[y : y + s, f * s : (f + 1) * s] = img
        y += s
    return Image.fromarray(out), s0, len(mips)


if __name__ == "__main__":
    for t in sys.argv[1:]:
        im, s0, n = atlas(int(t, 16))
        dst = os.path.join(FRONTEND_DIR, f"env_{t.lower()}.png")
        im.save(dst)
        print(dst, im.size, "face", s0, "mips", n)
