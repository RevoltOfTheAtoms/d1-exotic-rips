"""Setting the project up: where the dump and the Oodle DLL are, the Bungie API key, and checking it all works.

Used by both the window (gui.py) and the command line (d1rip.py). Locations are saved in d1rip.settings.json; the
API key in .secrets/bungie_api_key.txt. Neither is ever committed.
"""

import importlib.util
import os
import shutil
import subprocess
import sys

from d1kit import config, locate, manifest

VIEWER_IMAGES = ("inspect_bg.png", "env_80a7451f.png", "env_80a0856c.png")  # ripped by site/viewer_assets.py
PROBE_TAG = 0x80AA8380  # any real package entry: reading it proves the dump + Oodle work end to end


class SetupError(Exception):
    """Something the user needs to fix; the message says what."""


# --- requirements ---------------------------------------------------------------------------------------------------


def missing_packages():
    return [pip for mod, pip in (("numpy", "numpy"), ("PIL", "pillow")) if importlib.util.find_spec(mod) is None]


def install_packages(log=print):
    """pip-install requirements.txt if anything is missing."""
    if not missing_packages():
        return
    log("  installing Python packages (numpy, pillow)...")
    req = os.path.join(config.WORK, "requirements.txt")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", req])


# --- the dump --------------------------------------------------------------------------------------------------------


def describe(info):
    """'Destiny | CUSA00568 | disc v01.00' style summary of a locate.inspect_dump() result."""
    kinds = [k for k in ("disc", "patch") if info[k]]
    return f"{info['title'] or 'Destiny'} | {info['title_id']} | {' + '.join(kinds)} v{info['version']}"


def inspect_folder(path):
    """locate.inspect_dump(), also accepting the packages/ folder itself or a parent holding one dump."""
    if not path or not os.path.isdir(path):
        return None
    if os.path.basename(os.path.normpath(path)).lower() == "packages":
        path = os.path.dirname(os.path.normpath(path))
    info = locate.inspect_dump(path)
    if info:
        return info
    for d in sorted(os.listdir(path)):  # a folder that holds the dump folder(s)
        sub = os.path.join(path, d)
        if os.path.isdir(sub):
            info = locate.inspect_dump(sub)
            if info:
                return info
    return None


def current_paths():
    """(disc folder, patch folder, oodle dll) as configured now."""
    return config.DISC_ROOT, config.PATCH_ROOT, config.OODLE_DLL


def autodetect(log=print):
    """Find the dump and the Oodle DLL. Returns (disc, patch, oodle); any may be None."""
    log("  looking for your Destiny 1 dump...")
    disc, patch = locate.pick_dump(locate.find_dumps(config.WORK))
    oodle = config.OODLE_DLL if os.path.isfile(config.OODLE_DLL) else locate.find_oodle(config.WORK, (disc, patch))
    return disc, patch, oodle


def save_paths(disc=None, patch=None, oodle=None):
    """Validate and remember the locations. The DLL is copied into oodle/ so it stays available. Raises SetupError."""
    values = {}
    if disc:
        info = inspect_folder(disc)
        if not info or not info["disc"]:
            raise SetupError(
                f"No Destiny 1 PS4 disc dump in {disc} (expected a packages/ folder with ps4_*.pkg files)."
            )
        values["disc"] = info["path"]
    if patch:
        info = inspect_folder(patch)
        if not info or not info["patch"]:
            raise SetupError(f"No Destiny 1 PS4 patch in {patch} (expected packages/ with patch files, e.g. *_1.pkg).")
        values["patch"] = info["path"]
    if oodle:
        if not os.path.isfile(oodle) or os.path.basename(oodle).lower() != locate.DLL:
            raise SetupError(f"That isn't {locate.DLL}: {oodle}")
        if os.path.normcase(os.path.abspath(oodle)) != os.path.normcase(config.DEFAULT_OODLE):
            os.makedirs(os.path.dirname(config.DEFAULT_OODLE), exist_ok=True)
            shutil.copyfile(oodle, config.DEFAULT_OODLE)
    config.save_settings(**values)


# On Linux, Oodle 3 runs through linoodle (as tiger-pkg does): liblinoodle3.so loads oo2core_3_win64.dll itself.
# Fetched from the tiger-pkg repository, pinned to the file this project was tested with.
LINOODLE_URL = "https://raw.githubusercontent.com/v4nguard/tiger-pkg/main/liblinoodle3.so"
LINOODLE_SHA256 = "0167cfd2b31623ce15afd129c3ad568776d63af223824ab085254b7ea0730e35"


def ensure_platform_oodle(log=print):
    """Linux: download liblinoodle3.so next to the DLL if it's missing. Windows: nothing to do. Others: unsupported."""
    import hashlib
    import urllib.request

    from d1kit.pkg.package import LINUX_LIB

    if sys.platform == "win32":
        return
    if not sys.platform.startswith("linux"):
        raise SetupError("This project supports Windows and x86-64 Linux only.")
    target = os.path.join(os.path.dirname(config.OODLE_DLL), LINUX_LIB)
    if os.path.isfile(target):
        return
    log(f"  downloading {LINUX_LIB} (Oodle 3 for Linux, from tiger-pkg)")
    with urllib.request.urlopen(LINOODLE_URL, timeout=120) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != LINOODLE_SHA256:
        raise SetupError(f"{LINUX_LIB} from tiger-pkg has changed since this project was tested; not using it.")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)


def test_read():
    """Read one real package entry: proves the dump and Oodle work together. Raises SetupError."""
    from d1kit.pkg import store, tags

    store.reset()
    tags.reset()
    try:
        if len(tags.read(PROBE_TAG)) > 0:
            return
    except Exception as ex:  # report, don't crash: this is a diagnostic
        raise SetupError(f"Couldn't read the game files ({ex.__class__.__name__}: {ex}).") from ex
    raise SetupError("Couldn't read the game files.")


# --- the check -------------------------------------------------------------------------------------------------------


def missing_viewer_images():
    return [f for f in VIEWER_IMAGES if not os.path.isfile(os.path.join(config.FRONTEND_DIR, f))]


def status():
    """[(label, ok, detail)] for everything the build needs, for the window or the command line."""
    disc_info = inspect_folder(config.DISC_ROOT)
    patch_info = inspect_folder(config.PATCH_ROOT)
    rows = [
        (
            "Python packages",
            not missing_packages(),
            "installed" if not missing_packages() else "numpy / pillow missing",
        ),
        ("Disc dump", bool(disc_info and disc_info["disc"]), describe(disc_info) if disc_info else "not found"),
        ("1.33 patch", bool(patch_info and patch_info["patch"]), describe(patch_info) if patch_info else "not found"),
        (
            "Oodle DLL",
            os.path.isfile(config.OODLE_DLL),
            config.OODLE_DLL if os.path.isfile(config.OODLE_DLL) else "not found",
        ),
        ("Bungie API key", bool(manifest.load_api_key()), "saved" if manifest.load_api_key() else "not set"),
    ]
    return rows


def check(log=print):
    """Print the status checklist (and test reading the dump); returns the number of problems."""
    problems = 0
    for label, ok, detail in status():
        problems += not ok
        log(f"  [{'ok  ' if ok else 'MISSING'}] {label:<16} {detail}")
    if not problems:
        try:
            test_read()
            log("  [ok  ] Reading the dump  works")
        except SetupError as ex:
            problems += 1
            log(f"  [FAIL] Reading the dump  {ex}")
    log("All good." if not problems else f"{problems} thing(s) to fix.")
    return problems
