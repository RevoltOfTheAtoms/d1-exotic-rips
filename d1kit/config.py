"""Where things are: your PS4 dump, the Oodle DLL, reference data and this project's output folders.

You normally don't set anything: `py d1rip.py setup` (or start.bat) finds your dump and the Oodle DLL and saves the
locations in d1rip.settings.json next to this project. Each value is taken from, in order:

    1. an environment variable    D1_DISC, D1_PATCH, D1_OODLE    (optional overrides)
    2. d1rip.settings.json        {"disc": ..., "patch": ..., "oodle": ...}
    3. the default layout         the dump folders CUSA00568/ and CUSA00568-patch/ next to this project,
                                  the DLL at oodle/oo2core_3_win64.dll

D1_BUILD picks the game version: 1.33 (default, disc + final patch) or 1.01 (bare disc).
"""

import json
import os

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the project folder
ROOT = os.path.dirname(WORK)
SETTINGS_FILE = os.path.join(WORK, "d1rip.settings.json")
DEFAULT_OODLE = os.path.join(WORK, "oodle", "oo2core_3_win64.dll")


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    """Merge values into d1rip.settings.json and apply them to this process (reload())."""
    data = load_settings()
    data.update({k: v for k, v in values.items() if v})
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    reload()


def reload():
    """(Re)compute the dump and Oodle paths. Call before any package is opened (setup does)."""
    global DISC_ROOT, PATCH_ROOT, BASE_DIR, PATCH_DIR, OODLE_DLL, PKG_DIR, SEARCH
    # saved paths that don't exist here (e.g. a Windows path seen from Linux) are ignored
    s = {k: v for k, v in load_settings().items() if isinstance(v, str) and os.path.exists(v)}
    DISC_ROOT = os.environ.get("D1_DISC") or s.get("disc") or os.path.join(ROOT, "CUSA00568")
    PATCH_ROOT = os.environ.get("D1_PATCH") or s.get("patch") or os.path.join(ROOT, "CUSA00568-patch")
    BASE_DIR = os.path.join(DISC_ROOT, "packages")
    PATCH_DIR = os.path.join(PATCH_ROOT, "packages")
    # The packages use legacy (pre-Kraken) Oodle compression; only oo2core_3 decodes it. Not included: see README.
    OODLE_DLL = os.environ.get("D1_OODLE") or s.get("oodle") or DEFAULT_OODLE
    # 1.33 reads the patch stack (newest patch file per package wins); 1.01 the bare disc.
    PKG_DIR = PATCH_DIR if BUILD == "1.33" else BASE_DIR
    SEARCH = [PATCH_DIR, BASE_DIR] if BUILD == "1.33" else [BASE_DIR]


BUILD = os.environ.get("D1_BUILD", "1.33")
TAG = BUILD.replace(".", "")  # "133"
reload()

# Output folders (all ignored by git)
EXPORT_DIR = os.path.join(WORK, "export" if BUILD == "1.01" else f"export_{TAG}")  # one folder per weapon
SITE_DIR = os.path.join(WORK, "preview" if BUILD == "1.01" else f"preview_{TAG}")  # the built viewer site
CACHE_DIR = os.path.join(WORK, "cache")  # small lookup caches, safe to delete
FRONTEND_DIR = os.path.join(WORK, "frontend")  # the website: page template, game lighting, vendored libraries
REFERENCE_DIR = os.path.join(WORK, "reference")  # downloaded reference data
SECRETS_DIR = os.path.join(WORK, ".secrets")  # never committed
API_KEY_FILE = os.path.join(SECRETS_DIR, "bungie_api_key.txt")

# Display text (names, perks, stats, lore) isn't in the game files: the game downloads it from Bungie. It comes from
# Bungie's Destiny 1 manifest, fetched fresh with your API key (d1kit/manifest.py); 8,609 items, matching the 1.33
# item definitions one for one.
MANIFEST_DIR = os.path.join(REFERENCE_DIR, "bungie-manifest")

# item definition (class 80801806): offset of the item hash, per build
ITEM_HASH_OFF = 0x40 if BUILD == "1.01" else 0x78


def manifest_file(table):
    """Path of a manifest table ('InventoryItem', 'TalentGrid', 'SandboxPerk', 'Stat', 'StatGroup', 'GrimoireCard')."""
    return os.path.join(MANIFEST_DIR, f"Destiny{table}Definition.json")
