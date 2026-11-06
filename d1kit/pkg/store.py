"""Open the dump's packages (newest patch file wins) and read the investment tables that tie items to models."""

import glob
import os
import re
import struct

from d1kit import config
from d1kit.pkg.package import Oodle, Package

_od = None
_pkgs = {}
_latest = None
_tables = {}

# Investment tables by tag class, named by their 1.01 entry number in investment_globals_012c (1.33 moved them to
# 012f): #40 gear-art arrangements, #96 one item hash per arrangement, #81 dyes, ...
TABLE_CLASS = {
    26: 0x808034C7,
    35: 0x808033C3,
    40: 0x808034D7,
    41: 0x80803420,
    44: 0x80803483,
    81: 0x80801933,
    92: 0x808017EC,
    94: 0x808018C2,
    96: 0x808016FE,
    99: 0x80801906,
    101: 0x808017FE,
}


def oodle():
    global _od
    if _od is None:
        _od = Oodle(config.OODLE_DLL)
    return _od


def latest_files():
    """package stem -> path of its newest patch file across SEARCH (patch dir before base)."""
    global _latest
    if _latest is None:
        _latest = {}
        for d in reversed(config.SEARCH):
            for path in glob.glob(os.path.join(d, "*.pkg")):
                m = re.match(r"(.+)_(\d+)\.pkg$", os.path.basename(path))
                if m and (m[1] not in _latest or int(m[2]) >= _latest[m[1]][0]):
                    _latest[m[1]] = (int(m[2]), path)
        _latest = {k: v[1] for k, v in _latest.items()}
    return _latest


def pkg(name):
    """Open a package by file name; 'stem_0.pkg' (or a bare stem) means the newest patch of that package."""
    if name not in _pkgs:
        if os.path.isabs(name):
            path = name
        else:
            stem = re.sub(r"_\d+\.pkg$", "", name)
            path = latest_files().get(stem) or os.path.join(config.PKG_DIR, name)
        _pkgs[name] = Package(path, oodle(), config.SEARCH)
    return _pkgs[name]


def class_entries(cls, stem_part="investment_globals"):
    """[(package, entry)] for every entry of a tag class in the build's packages whose name contains stem_part."""
    out = []
    for stem, path in sorted(latest_files().items()):
        if stem_part in stem:
            p = pkg(path)
            out += [(p, e) for e in p.entries if e["reference"] == cls]
    return out


def table(idx):
    """Investment table by its 1.01 012c entry number (found by class, so it works on any build)."""
    if idx not in _tables:
        ((p, e),) = class_entries(TABLE_CLASS[idx])
        d = p.read_entry(e["index"])
        # 1.33 added a second array to some tables (#40, #44), moving the main array's header past 0x20.
        # Re-base it to 0x20 like 1.01; element pointers are relative, so they stay valid.
        h = 0x10 + struct.unpack_from("<Q", d, 0x10)[0]
        if h != 0x20:
            d = d[:0x10] + struct.pack("<QQ", 0x10, 0) + d[h:]
        _tables[idx] = d
    return _tables[idx]


def table_raw(idx):
    """The table exactly as stored (no re-basing)."""
    ((p, e),) = class_entries(TABLE_CLASS[idx])
    return p.read_entry(e["index"])


def reset():
    """Forget opened packages and lookups (after the dump or Oodle location changes)."""
    global _od, _latest
    _od, _latest = None, None
    _pkgs.clear()
    _tables.clear()
