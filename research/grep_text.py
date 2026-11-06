"""Search decompressed package entries (and optionally eboot.bin) for text in several encodings.

usage: grep_text.py "<pkg glob>" word [word ...]
"""

import fnmatch
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import PKG_DIR
from d1kit.pkg.store import latest_files, pkg

pattern_glob, *words = sys.argv[1:]
needles = []
for w in words:
    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        needles.append((w, enc, w.encode(enc)))
        needles.append((w, enc + "/lower", w.lower().encode(enc)))
        needles.append((w, enc + "/upper", w.upper().encode(enc)))

eboot = os.path.join(os.path.dirname(PKG_DIR), "eboot.bin")
with open(eboot, "rb") as f:
    data = f.read()
for w, enc, n in needles:
    if n in data:
        print(f"eboot.bin '{w}' {enc} @0x{data.find(n):x}", flush=True)

# newest patch file of each package for the build (D1_BUILD), matched on its file name
for path in sorted(p for p in latest_files().values() if fnmatch.fnmatch(os.path.basename(p), pattern_glob)):
    p = pkg(path)
    for e in p.entries:
        if e["size"] == 0 or e["type"] in (512, 520):
            continue
        try:
            d = p.read_entry(e["index"])
        except Exception:
            continue
        for w, enc, n in needles:
            pos = d.find(n)
            if pos >= 0:
                print(
                    f"{os.path.basename(path)} idx={e['index']} t{e['type']}/s{e['subtype']} "
                    f"class={e['reference']:08x} '{w}' {enc} @0x{pos:x}",
                    flush=True,
                )
    p._cache.clear()
