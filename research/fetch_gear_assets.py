"""Fetch Bungie's D1 gear asset data (web models) for items, to read per-part dye choices.

usage: py tools/fetch_gear_assets.py <item hash> [...]
Reads the API key from Workspace/.secrets/bungie_api_key.txt (never printed). Downloads into reference/d1-gear-assets/:
  manifest.json                    D1 manifest index (needs the key)
  gear_asset_db.sqlite             mobile gear asset database (static file on bungie.net)
  items/<hash>.json                the item's gear asset entry (geometry / texture file names)
  geometry/<name>                  TGX geometry containers (static files on bungie.net)
"""

import io
import json
import os
import sqlite3
import struct
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import WORK

BNET = "https://www.bungie.net"
OUT = os.path.join(WORK, "reference", "d1-gear-assets")
KEY_FILE = os.path.join(WORK, ".secrets", "bungie_api_key.txt")


def key():
    with open(KEY_FILE, encoding="utf-8") as f:
        return f.read().strip()


def get(url, api=False):
    req = urllib.request.Request(url, headers={"X-API-Key": key()} if api else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def manifest():
    p = os.path.join(OUT, "manifest.json")
    if not os.path.exists(p):
        os.makedirs(OUT, exist_ok=True)
        data = json.loads(get(f"{BNET}/d1/Platform/Destiny/Manifest/", api=True))
        if data.get("ErrorCode") != 1:
            raise SystemExit(f"manifest request failed: {data.get('ErrorStatus')} {data.get('Message')}")
        json.dump(data["Response"], open(p, "w"), indent=1)
    return json.load(open(p))


def gear_db():
    p = os.path.join(OUT, "gear_asset_db.sqlite")
    if not os.path.exists(p):
        dbs = manifest()["mobileGearAssetDataBases"]
        path = max(dbs, key=lambda d: d["version"])["path"]
        raw = get(BNET + path)
        if raw[:2] == b"PK":  # zipped sqlite
            z = zipfile.ZipFile(io.BytesIO(raw))
            raw = z.read(z.namelist()[0])
        open(p, "wb").write(raw)
    return sqlite3.connect(p)


def signed(h):
    return struct.unpack("<i", struct.pack("<I", h))[0]


def item_assets(item_hash):
    """The item's gear asset JSON (content: geometry, textures, plated textures, dye index sets)."""
    p = os.path.join(OUT, "items", f"{item_hash}.json")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        db = gear_db()
        tables = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
        table = next(t for t in tables if "GearAsset" in t)
        row = db.execute(f"select json from {table} where id in (?, ?)", (signed(item_hash), item_hash)).fetchone()
        if row is None:
            return None
        open(p, "w").write(row[0] if isinstance(row[0], str) else row[0].decode())
    return json.load(open(p))


def geometry(name):
    p = os.path.join(OUT, "geometry", name)
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(get(f"{BNET}/common/destiny_content/geometry/platform/mobile/geometry/{name}"))
    return p


if __name__ == "__main__":
    for h in sys.argv[1:]:
        a = item_assets(int(h))
        if a is None:
            print(h, "not in the gear asset database")
            continue
        names = [g for c in a.get("content", []) for g in c.get("geometry", [])]
        for n in names:
            geometry(n)
        print(h, "geometry files:", names)
