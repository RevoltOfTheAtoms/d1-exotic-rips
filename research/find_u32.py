"""Find little-endian u32 values in decompressed package entries.

usage: find_u32.py "<pkg glob>" <value> [value ...]   (decimal or 0x hex)
"""

import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import PKG_DIR
from d1kit.pkg.store import pkg

pattern_glob, *vals = sys.argv[1:]
needles = [(v, struct.pack("<I", int(v, 0))) for v in vals]
for path in sorted(glob.glob(os.path.join(PKG_DIR, pattern_glob))):
    p = pkg(path)
    for e in p.entries:
        if e["size"] == 0 or e["type"] in (512, 520):
            continue
        try:
            d = p.read_entry(e["index"])
        except Exception:
            continue
        for v, n in needles:
            pos = d.find(n)
            while pos >= 0:
                print(
                    f"{os.path.basename(path)} idx={e['index']} t{e['type']}/s{e['subtype']} "
                    f"class={e['reference']:08x} size={e['size']} {v} @0x{pos:x}",
                    flush=True,
                )
                pos = d.find(n, pos + 1)
    p._cache.clear()
