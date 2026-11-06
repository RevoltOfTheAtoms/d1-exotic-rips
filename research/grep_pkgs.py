"""Case-insensitive search of decompressed package entries (ASCII and UTF-16LE).

usage: grep_pkgs.py "<pkg glob>" word [word ...]
"""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import PKG_DIR
from d1kit.pkg.store import pkg

if __name__ == "__main__":
    pattern_glob, *words = sys.argv[1:]
    needles = []
    for w in words:
        w = w.lower()
        needles += [(w, "a", w.encode()), (w, "u16", w.encode("utf-16-le"))]
    for path in sorted(glob.glob(os.path.join(PKG_DIR, pattern_glob))):
        p = pkg(path)
        for e in p.entries:
            if e["size"] == 0 or e["type"] in (512, 520):  # skip audio
                continue
            try:
                d = p.read_entry(e["index"]).lower()
            except Exception:
                continue
            for w, enc, n in needles:
                pos = d.find(n)
                if pos >= 0:
                    ctx = d[max(0, pos - 24) : pos + 48].replace(b"\0", b"|")
                    print(
                        f"{os.path.basename(path)} idx={e['index']} t{e['type']}/s{e['subtype']} "
                        f"'{w}' {enc} @0x{pos:x} {ctx!r}",
                        flush=True,
                    )
        p._cache.clear()
        print(f"# done {os.path.basename(path)}", file=sys.stderr, flush=True)
