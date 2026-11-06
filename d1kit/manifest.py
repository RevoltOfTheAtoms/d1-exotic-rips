"""Bungie's Destiny 1 manifest: the text the game doesn't store (names, perks, stats, lore), fetched at build time.

Needs a Bungie API key (free, https://www.bungie.net/en/Application). The key is used only while building: the
website gets the text it needs written into its pages and never contains or needs the key.

Bungie serves the manifest as a zipped SQLite database. The tables the project uses are written as JSON files to
config.MANIFEST_DIR ({hash: definition}, sorted by hash), plus a version file. A later build downloads again only when
Bungie's version has changed.
"""

import io
import json
import os
import sqlite3
import tempfile
import urllib.error
import urllib.request
import zipfile

from d1kit import config

MANIFEST_API = "https://www.bungie.net/d1/Platform/Destiny/Manifest/"
# The D1 manifest endpoint doesn't check keys; this one does (2102 = missing, 2101 = invalid or expired, 1 = ok).
KEY_CHECK_API = "https://www.bungie.net/Platform/User/GetAvailableThemes/"
TABLES = ("InventoryItem", "TalentGrid", "SandboxPerk", "Stat", "StatGroup", "GrimoireCard")
VERSION_FILE = os.path.join(config.MANIFEST_DIR, "version.txt")


class ManifestError(Exception):
    """A problem the user can fix (no key, wrong key, no connection); the message says what to do."""


def load_api_key():
    try:
        with open(config.API_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_api_key(key):
    os.makedirs(config.SECRETS_DIR, exist_ok=True)
    with open(config.API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key.strip())


def _get(url, key=None, timeout=60):
    req = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _api(url, key):
    try:
        return json.loads(_get(url, key))
    except urllib.error.HTTPError as ex:
        raise ManifestError(f"Bungie refused the request ({ex.code}). Check the API key.") from ex
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise ManifestError(f"Couldn't reach bungie.net ({ex}). Check the internet connection.") from ex


def check_key(key):
    """Raise ManifestError unless Bungie accepts the API key."""
    if not key:
        raise ManifestError("A Bungie API key is needed to download the item names, perks and lore.")
    d = _api(KEY_CHECK_API, key)
    if d.get("ErrorCode") != 1:
        raise ManifestError(f"Bungie didn't accept the API key: {d.get('Message') or d.get('ErrorStatus')}")


def current_version(key):
    """(version, sqlite path on bungie.net) of Bungie's English D1 manifest. Raises ManifestError."""
    check_key(key)
    d = _api(MANIFEST_API, key)
    if d.get("ErrorStatus") != "Success":
        raise ManifestError(f"Bungie said: {d.get('Message') or d.get('ErrorStatus')}. Check the API key.")
    r = d["Response"]
    return r["version"], r["mobileWorldContentPaths"]["en"]


def installed_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def is_installed():
    return all(os.path.isfile(config.manifest_file(t)) for t in TABLES)


def _write_tables(db_path):
    con = sqlite3.connect(db_path)
    try:
        for table in TABLES:
            rows = {}
            for row_id, blob in con.execute(f"SELECT id, json FROM Destiny{table}Definition"):
                rows[row_id & 0xFFFFFFFF] = json.loads(blob)  # ids are signed 32-bit hashes
            data = {str(h): rows[h] for h in sorted(rows)}
            with open(config.manifest_file(table), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    finally:
        con.close()


def update(key, log=print):
    """Make sure the manifest is installed and current. Returns the version. Raises ManifestError."""
    version, path = current_version(key)
    if is_installed() and installed_version() == version:
        log(f"  item text up to date (Bungie manifest {version})")
        return version
    log(f"  downloading item text from Bungie (manifest {version}, about 6 MB)")
    try:
        blob = _get("https://www.bungie.net" + path, timeout=300)
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise ManifestError(f"Download from bungie.net failed ({ex}).") from ex
    os.makedirs(config.MANIFEST_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        z.extract(name, tmp)
        _write_tables(os.path.join(tmp, name))
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(version)
    log(f"  item text installed ({len(TABLES)} tables)")
    return version
