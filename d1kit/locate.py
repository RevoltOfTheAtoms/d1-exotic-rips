"""Find the user's Destiny 1 dump and the Oodle DLL, so nobody has to type paths.

A folder is recognised by what's in it, not by its name: a Destiny 1 PS4 dump has `packages/` holding
`ps4_investment_globals_*.pkg` files with Tiger header version 24 and platform 7 (PS4). The disc's packages have
patch number 0; the update's have 1 and up. A dump where the patch was merged onto the disc counts as both.

Only likely places are searched, a few levels deep. Folders that belong to other games or to Steam are skipped by
name and never opened: this project only ever reads Destiny 1 PS4 data.
"""

import glob
import os
import re
import string
import struct

SKIP = re.compile(
    r"steam|destiny ?2|bungie|battle\.net|epic games|windowsapps|program files|programdata|\$recycle|"
    r"system volume information|^windows$|appdata|node_modules|\.git$|__pycache__",
    re.I,
)
SIGNATURE = "ps4_investment_globals_*.pkg"
DLL = "oo2core_3_win64.dll"


def _walk(top, depth):
    """Directories under top, breadth first, at most `depth` levels down, skipping SKIP names."""
    level = [top]
    for _ in range(depth + 1):
        nxt = []
        for d in level:
            yield d
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False) and not SKIP.search(e.name):
                            nxt.append(e.path)
            except OSError:
                continue
        level = nxt


def _search_roots(project):
    """Likely places, nearest first: around the project, then the user's folders, then drive roots."""
    home = os.path.expanduser("~")
    roots = [(os.path.dirname(project), 2), (project, 2)]
    for sub in ("Desktop", "Downloads", "Documents", "OneDrive"):
        roots.append((os.path.join(home, sub), 4))
    if os.name == "nt":
        roots += [(f"{c}:\\", 3) for c in string.ascii_uppercase if os.path.isdir(f"{c}:\\")]
    else:
        roots += [(home, 3), ("/mnt", 3), ("/media", 3)]
    seen, out = set(), []
    for r, depth in roots:
        key = os.path.normcase(os.path.abspath(r))
        if os.path.isdir(r) and key not in seen:
            seen.add(key)
            out.append((r, depth))
    return out


def param_sfo(folder):
    """{'TITLE_ID': ..., 'APP_VER': ..., 'TITLE': ...} from sce_sys/param.sfo, or {}."""
    path = os.path.join(folder, "sce_sys", "param.sfo")
    try:
        with open(path, "rb") as f:
            d = f.read()
        magic, _, key_tab, data_tab, n = struct.unpack_from("<4sIIII", d, 0)
        if magic != b"\0PSF":
            return {}
        out = {}
        for i in range(n):
            ko, fmt, length, _, do = struct.unpack_from("<HHIII", d, 0x14 + i * 16)
            key = d[key_tab + ko : d.index(b"\0", key_tab + ko)].decode("latin-1")
            if fmt in (0x0204, 0x0004):  # UTF-8 string
                out[key] = d[data_tab + do : data_tab + do + length].rstrip(b"\0").decode("utf-8", "replace")
        return out
    except (OSError, struct.error, ValueError):
        return {}


def inspect_dump(folder):
    """If `folder` is a Destiny 1 PS4 dump: dict(path, disc, patch, title_id, version, title). Else None."""
    pk = os.path.join(folder, "packages")
    files = glob.glob(os.path.join(pk, SIGNATURE))
    if not files:
        return None
    patches = set()
    for path in files:
        try:
            with open(path, "rb") as f:
                h = f.read(0x24)
            version, platform = struct.unpack_from("<HH", h, 0)
            (patch,) = struct.unpack_from("<H", h, 0x20)
        except (OSError, struct.error):
            continue
        if version == 24 and platform == 7:
            patches.add(patch)
    if not patches:
        return None
    sfo = param_sfo(folder)
    return dict(
        path=folder,
        disc=0 in patches,
        patch=max(patches) > 0,
        title_id=sfo.get("TITLE_ID", "?"),
        version=sfo.get("APP_VER", "?"),
        title=sfo.get("TITLE", ""),
    )


def find_dumps(project, stop_when_complete=True):
    """Destiny 1 PS4 dumps in the likely places: [inspect_dump() dicts], nearest first. Stops after the place where
    both a disc and a patch have been found, unless stop_when_complete is False."""
    found, seen = [], set()
    for root, depth in _search_roots(project):
        if stop_when_complete and all(pick_dump(found)):
            break
        for d in _walk(root, depth):
            if os.path.isdir(os.path.join(d, "packages")):
                key = os.path.normcase(os.path.abspath(d))
                if key in seen:
                    continue
                seen.add(key)
                info = inspect_dump(d)
                if info:
                    found.append(info)
    return found


def pick_dump(found):
    """(disc folder, patch folder) from find_dumps(); either can be None."""
    discs = [f for f in found if f["disc"]]
    patches = sorted((f for f in found if f["patch"]), key=lambda f: f["version"], reverse=True)
    disc = discs[0]["path"] if discs else None
    patch = patches[0]["path"] if patches else None
    if disc is None and patch is not None and patches[0]["disc"]:
        disc = patch  # patch merged onto the disc in one folder
    return disc, patch


def find_oodle(project, near=()):
    """Path of oo2core_3_win64.dll in the likely places (where the user copied it), or None. Game installs (Steam,
    Destiny 2, ...) are never searched: users copy the DLL out themselves (README: The Oodle DLL)."""
    home = os.path.expanduser("~")
    roots = [(project, 3)] + [(os.path.dirname(p), 3) for p in near if p]
    roots += [(os.path.join(home, s), 4) for s in ("Downloads", "Desktop", "Documents")]
    for root, depth in roots:
        if not os.path.isdir(root):
            continue
        for d in _walk(root, depth):
            p = os.path.join(d, DLL)
            if os.path.isfile(p):
                return p
    return None
