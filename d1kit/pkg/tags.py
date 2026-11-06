"""Tag hash helpers: tag = 0x80800000 + (pkg_id << 13) + entry index."""

import bisect
import hashlib
import json
import os
import struct

from d1kit import config
from d1kit.pkg.store import class_entries, latest_files, pkg

_ids = None
_lookup = None


def pkg_ids():
    """pkg_id -> package filename (newest patch for the build), cached in cache/pkg_ids_<build>_<dump>.json (one cache
    per dump location, so pointing the project at another dump never reuses a stale list)."""
    global _ids
    if _ids is None:
        dump = hashlib.sha1("|".join(os.path.normcase(d) for d in config.SEARCH).encode()).hexdigest()[:8]
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        cache = os.path.join(config.CACHE_DIR, f"pkg_ids_{config.TAG}_{dump}.json")
        if os.path.exists(cache):
            _ids = {int(k): v for k, v in json.load(open(cache)).items()}
        else:
            _ids = {}
            for path in latest_files().values():
                with open(path, "rb") as f:
                    h = f.read(0x24)
                (pid,) = struct.unpack_from("<H", h, 4)
                _ids[pid] = os.path.basename(path)
            json.dump(_ids, open(cache, "w"), indent=0)
    return _ids


def split(tag):
    return (tag - 0x80800000) >> 13, (tag - 0x80800000) & 0x1FFF


def entry(tag):
    pid, idx = split(tag)
    p = pkg(pkg_ids()[pid])
    return p, p.entries[idx]


def read(tag):
    p, e = entry(tag)
    return p.read_entry(e["index"])


def is_tag(v):
    if not (0x80800000 <= v < 0x81000000) or v & 0x1FFF > 0x1FFF:
        return False
    pid, idx = split(v)
    ids = pkg_ids()
    return pid in ids and idx < pkg(ids[pid]).entry_count


def asset_lookup(h):
    """Gear asset hash -> tag via sorted (hash, tag) u32 pair tables: class 80800341 (investment_assets_0135 #1
    on 1.01); 1.33 adds class 80803aaa (investment_assets_013f) and holds most gear assets there."""
    global _lookup
    if _lookup is None:
        pairs = {}
        for cls in (0x80800341, 0x80803AAA):
            for p, e in class_entries(cls, "investment_assets"):
                if e["type"] != 16 or e["size"] < 0x30:
                    continue
                d = p.read_entry(e["index"])
                (n,) = struct.unpack_from("<Q", d, 0x20)
                if 0x30 + n * 8 > len(d):
                    continue
                v = struct.unpack_from(f"<{n * 2}I", d, 0x30)
                pairs.update(zip(v[0::2], v[1::2]))
        keys = sorted(pairs)
        _lookup = (keys, [pairs[k] for k in keys])
    keys, vals = _lookup
    i = bisect.bisect_left(keys, h)
    return vals[i] if i < len(keys) and keys[i] == h else None


def tags_in(d):
    """All (offset, tag) u32 values in data that look like valid tag hashes."""
    out = []
    for o in range(0, len(d) - 3, 4):
        (v,) = struct.unpack_from("<I", d, o)
        if 0x80800000 <= v < 0x81000000 and is_tag(v):
            out.append((o, v))
    return out


def reset():
    """Forget cached lookups (after the dump location changes)."""
    global _ids, _lookup
    _ids = _lookup = None
