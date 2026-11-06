"""Print printable strings (>= minlen) from every non-audio entry of a package.

usage: strings_pkg.py <pkg> [minlen] [types comma list]
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.pkg.store import pkg

p = pkg(sys.argv[1])
minlen = int(sys.argv[2]) if len(sys.argv) > 2 else 8
types = {int(t) for t in sys.argv[3].split(",")} if len(sys.argv) > 3 else None
rx = re.compile(rb"[\x20-\x7e]{%d,}" % minlen)
for e in p.entries:
    if e["size"] == 0 or e["type"] in (512, 520) or (types and e["type"] not in types):
        continue
    try:
        d = p.read_entry(e["index"])
    except Exception:
        continue
    for m in rx.finditer(d):
        print(
            f"{e['index']}\tt{e['type']}/s{e['subtype']}\t{e['reference']:08x}\t0x{m.start():x}\t{m.group().decode()}"
        )
