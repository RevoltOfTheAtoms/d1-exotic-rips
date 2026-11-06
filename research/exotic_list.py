"""List exotic weapons present in the v1.01 client, named via the archived D1 manifest (nmlorg/destiny-db).

Writes analysis/exotic_weapons_v101.json and prints a table.
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (for d1kit)
from d1kit.config import WORK
from d1kit.pkg.store import pkg

ITEM_CLASS = 0x80801806  # per-item definition tag; u32 item hash @0x40

items = json.load(open(os.path.join(WORK, "reference", "destiny-db", "InventoryItem.json"), encoding="utf-8"))

client = {}
for name in [
    "ps4_investment_globals_012c_0.pkg",
    "ps4_investment_globals_012e_0.pkg",
    "ps4_investment_globals_012f_0.pkg",
]:
    p = pkg(name)
    for e in p.entries:
        if e["type"] == 16 and e["reference"] == ITEM_CLASS:
            d = p.read_entry(e["index"])
            h = struct.unpack_from("<I", d, 0x40)[0]
            client[h] = dict(pkg=name, index=e["index"], tag=f"{0x80800000 + (p.pkg_id << 13) + e['index']:08x}")

rows = []
for h, it in items.items():
    if it.get("itemType") != 3 or it.get("tierType") != 6:
        continue
    h = int(h)
    rows.append(
        dict(
            hash=h,
            name=it.get("itemName"),
            type=it.get("itemTypeName"),
            gearArt=it.get("equippingBlock", {}).get("gearArtArrangementIndex"),
            in_v101=h in client,
            client=client.get(h),
        )
    )
rows.sort(key=lambda r: (not r["in_v101"], r["type"] or "", r["name"] or ""))
out = os.path.join(WORK, "analysis", "exotic_weapons_v101.json")
json.dump(rows, open(out, "w"), indent=1)
print(
    f"client item defs: {len(client)}; archive exotic weapons: {len(rows)}; in v1.01: {sum(r['in_v101'] for r in rows)}"
)
for r in rows:
    print(f"{'Y' if r['in_v101'] else '-'}  {r['hash']:>10}  gearArt={r['gearArt']!s:>5}  {r['type']:<16} {r['name']}")
