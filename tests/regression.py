"""Regression check: re-export a set of weapons and compare every output file with a saved baseline.

    py tests/regression.py save    <dir>     export the reference set into <dir> (do this before a change)
    py tests/regression.py compare <dir>     export again into a temp folder and diff against <dir>
    py tests/regression.py compare <dir> --tolerance 1
                                             allow image values to differ by 1 (baselines made on another OS)

The reference set covers the special cases: shader-baked gear (Thorn, Khvostov), cube reflections (Gjallarhorn),
the lens fix (MIDA), approximations and skipped materials (Touch of Malice), glows (Invective, Thorn),
G-buffer surfaces (Patience and Time), decals (Ace of Spades), swords, Ice Breaker's fallback and a raid Adept item.
Exports are deterministic. Files are compared byte for byte, except: PNG images (also inside GLBs) by decoded pixels,
since zlib builds compress identical pixels differently (Windows vs Linux); JSON by parsed content (line endings).
Across operating systems NumPy versions can round a shader result differently (1 of ~4 million values was off by 1
between Windows and Ubuntu): use --tolerance 1 there.
"""

import filecmp
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from d1kit.export.weapon import export  # noqa: E402

REFERENCE_SET = [
    "3164616404",  # Thorn
    "1274330687",  # Gjallarhorn
    "3688594189",  # Touch of Malice
    "1346849289",  # MIDA Multi-Tool
    "1623420384",  # The Young Wolf's Howl
    "1389842216",  # Invective
    "3118679308",  # Ice Breaker
    "1288233773",  # Fatebringer (Adept)
    "3118679309",  # Patience and Time
    "1758882169",  # Khvostov 7G-0X
    "552354419",  # Ace of Spades
]


def export_set(out_dir):
    for h in REFERENCE_SET:
        export(h, out_dir)


def _png_pixels(data):
    import io

    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    return im.mode, im.size, np.asarray(im).tobytes()


def _glb_content(data):
    """A GLB's content without its byte layout: JSON (minus buffer offsets), accessor data, decoded images.
    PNG compression differs between zlib builds (e.g. Windows' zlib-ng vs Linux zlib) for identical pixels."""
    import json
    import struct

    (n,) = struct.unpack_from("<I", data, 12)
    g = json.loads(data[20 : 20 + n])
    binary = data[20 + n + 8 :]

    def view(i):
        v = g["bufferViews"][i]
        return binary[v.get("byteOffset", 0) : v.get("byteOffset", 0) + v["byteLength"]]

    accessors = [view(a["bufferView"]) for a in g["accessors"]]
    images = [_png_pixels(view(im["bufferView"])) for im in g["images"]]
    for key in ("bufferViews", "buffers"):
        g.pop(key)
    for a in g["accessors"]:
        a.pop("bufferView")
    for im in g["images"]:
        im.pop("bufferView")
    return g, accessors, images


def _images_equal(x, y, tolerance):
    if x[:2] != y[:2]:
        return False
    if x[2] == y[2]:
        return True
    import numpy as np

    d = np.abs(np.frombuffer(x[2], np.uint8).astype(np.int16) - np.frombuffer(y[2], np.uint8).astype(np.int16))
    return int(d.max()) <= tolerance


def same_content(pa, pb, tolerance=0):
    """Byte-identical, or identical once decoded (PNG / GLB / JSON); image values may differ by `tolerance`."""
    if filecmp.cmp(pa, pb, shallow=False):
        return True
    with open(pa, "rb") as f:
        a = f.read()
    with open(pb, "rb") as f:
        b = f.read()
    if pa.endswith(".png"):
        return _images_equal(_png_pixels(a), _png_pixels(b), tolerance)
    if pa.endswith(".glb"):
        ga, aa, ia = _glb_content(a)
        gb, ab, ib = _glb_content(b)
        return (
            ga == gb and aa == ab and len(ia) == len(ib) and all(_images_equal(x, y, tolerance) for x, y in zip(ia, ib))
        )
    if pa.endswith(".json"):
        import json

        return json.loads(a) == json.loads(b)
    return False


def diff_trees(a, b, tolerance=0):
    """[(relative path, problem)] for files whose content differs or that exist on one side only."""
    problems = []
    for root, _, files in os.walk(a):
        for f in files:
            pa = os.path.join(root, f)
            rel = os.path.relpath(pa, a)
            pb = os.path.join(b, rel)
            if not os.path.exists(pb):
                problems.append((rel, "missing in new export"))
            elif not same_content(pa, pb, tolerance):
                problems.append((rel, "differs"))
    for root, _, files in os.walk(b):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), b)
            if not os.path.exists(os.path.join(a, rel)):
                problems.append((rel, "new file"))
    return problems


def main():
    args = sys.argv[1:]
    tolerance = 0
    if "--tolerance" in args:
        i = args.index("--tolerance")
        tolerance = int(args[i + 1])
        del args[i : i + 2]
    if len(args) != 2 or args[0] not in ("save", "compare"):
        sys.exit(__doc__)
    mode, base = args
    if mode == "save":
        export_set(base)
        print(f"baseline saved in {base}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        export_set(tmp)
        problems = diff_trees(base, tmp, tolerance)
    n = sum(len(f) for _, _, f in os.walk(base))
    for rel, what in problems[:50]:
        print(f"  {what:<22} {rel}")
    print(f"{n} baseline files, {len(problems)} differences")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
