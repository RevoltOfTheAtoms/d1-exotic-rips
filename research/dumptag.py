"""Hexdump tags of a class (or an entry) from a package.

usage: dumptag.py <pkg> class <hex class> [n] [maxbytes]
       dumptag.py <pkg> idx <index> [maxbytes]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.pkg.store import pkg


def hexdump(d, n, base=0):
    for o in range(0, min(len(d), n), 16):
        row = d[o : o + 16]
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        words = " ".join(f"{int.from_bytes(row[i : i + 4], 'little'):08x}" for i in range(0, len(row), 4))
        print(f"  {base + o:05x}: {words:<36} {asc}")


if __name__ == "__main__":
    p = pkg(sys.argv[1])
    mode = sys.argv[2]
    if mode == "class":
        cls = int(sys.argv[3], 16)
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        mx = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x100
        hits = [e for e in p.entries if e["type"] == 16 and e["reference"] == cls][:n]
    else:
        hits = [p.entries[int(sys.argv[3])]]
        mx = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x200
    for e in hits:
        tag = 0x80800000 + (p.pkg_id << 13) + e["index"]
        print(f"idx {e['index']} tag {tag:08x} class {e['reference']:08x} size {e['size']}")
        hexdump(p.read_entry(e["index"]), mx)
