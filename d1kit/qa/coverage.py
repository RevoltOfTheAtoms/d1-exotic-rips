"""QA: how much of each weapon's plated surface samples atlas areas no plate covered (= unfinished texture).

usage: [D1_BUILD=1.33] py tools/check_coverage.py [slug ...]
Empty atlas pixels keep the exporter's fill: diffuse (128,128,128) and gearstack (0,128,255). For every textured
primitive, triangle UV centroids are sampled (area-weighted) and the share landing on empty pixels is reported.
"""

import json
import os
import struct
import sys

import numpy as np
from PIL import Image

from d1kit.config import EXPORT_DIR

ROOT = EXPORT_DIR


def glb_prims(path):
    b = open(path, "rb").read()
    (n,) = struct.unpack_from("<I", b, 12)
    j = json.loads(b[20 : 20 + n])
    blob = b[20 + n + 8 :]

    def acc(i):
        a = j["accessors"][i]
        bv = j["bufferViews"][a["bufferView"]]
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[a["componentType"]]
        arr = np.frombuffer(blob, dt, a["count"] * k, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
        return arr.reshape(-1, k) if k > 1 else arr

    for nd in j["nodes"]:
        if "mesh" not in nd:
            continue
        for pr in j["meshes"][nd["mesh"]]["primitives"]:
            name = j["materials"][pr["material"]]["name"]
            if name.startswith("canvas") and name[6:].isdigit() and "TEXCOORD_0" in pr["attributes"]:
                yield nd["name"], int(name[6:]), acc(pr["attributes"]["TEXCOORD_0"]), acc(pr["indices"]).reshape(-1, 3)


def check(slug):
    d = os.path.join(ROOT, slug)
    empty = {}
    total = bad = 0.0
    per_part = {}
    for part, canvas, uv, tri in glb_prims(os.path.join(d, f"{slug}.glb")):
        if canvas not in empty:
            dif = np.asarray(
                Image.open(os.path.join(d, "textures", "atlas", f"canvas{canvas}_diffuse.png")).convert("RGB")
            )
            gs = np.asarray(
                Image.open(os.path.join(d, "textures", "atlas", f"canvas{canvas}_gearstack.png")).convert("RGB")
            )
            empty[canvas] = (dif == (128, 128, 128)).all(-1) & (gs == (0, 128, 255)).all(-1)
        m = empty[canvas]
        h, w = m.shape
        a, b_, c = uv[tri[:, 0]], uv[tri[:, 1]], uv[tri[:, 2]]
        area = np.abs((b_[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b_[:, 1] - a[:, 1])) / 2
        cen = (a + b_ + c) / 3
        x = np.clip((cen[:, 0] % 1.0) * w, 0, w - 1).astype(int)
        y = np.clip((cen[:, 1] % 1.0) * h, 0, h - 1).astype(int)
        hit = m[y, x]
        total += area.sum()
        bad += area[hit].sum()
        if area.sum():
            pp = per_part.setdefault(part, [0.0, 0.0])
            pp[0] += area[hit].sum()
            pp[1] += area.sum()
    worst = sorted(((v[0] / v[1], k) for k, v in per_part.items() if v[1]), reverse=True)[:2]
    return (bad / total if total else 0.0), worst


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(s for s in os.listdir(ROOT) if os.path.exists(os.path.join(ROOT, s, f"{s}.glb")))
    rows = []
    for s in slugs:
        try:
            rows.append((check(s), s))
        except Exception as ex:
            print(f"{s}: error {ex}")
    for (share, worst), s in sorted(rows, reverse=True):
        flag = "  <-- unfinished" if share > 0.02 else ""
        print(f"{share * 100:5.1f}%  {s:<42} worst parts: {[(k, round(v * 100)) for v, k in worst if v > 0.01]}{flag}")
