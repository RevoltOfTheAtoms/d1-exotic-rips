"""Find tag arrays: field [u64 count][u64 rel] -> header at field+8+rel = [u64 count][u32 elemclass], data at +0x10.

usage: find_arrays.py "<pkg glob>" <min count> <max count>
"""

import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import PKG_DIR
from d1kit.pkg.store import pkg

pattern_glob, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
for path in sorted(glob.glob(os.path.join(PKG_DIR, pattern_glob))):
    p = pkg(path)
    for e in p.entries:
        if e["type"] != 16:
            continue
        d = p.read_entry(e["index"])
        for o in range(0, len(d) - 16, 8):
            cnt, rel = struct.unpack_from("<QQ", d, o)
            if not (lo <= cnt <= hi) or rel == 0 or rel > len(d):
                continue
            t = o + 8 + rel
            if t + 0x10 > len(d):
                continue
            c2, z, cls = struct.unpack_from("<III", d, t)
            t += 0x10
            if c2 == cnt and (cls >> 16) == 0x8080:
                stride = (len(d) - t) // cnt if cnt else 0
                print(
                    f"{os.path.basename(path)} idx={e['index']} class={e['reference']:08x} size={len(d)} "
                    f"field@{o:#x} count={cnt} elemclass={cls:08x} data@{t:#x} maxstride~{stride}",
                    flush=True,
                )
    p._cache.clear()
