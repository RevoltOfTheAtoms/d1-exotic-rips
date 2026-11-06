"""Weapon stats, perks and lore for the viewer.

Numbers come from the disc (v1.01, or v1.33 with D1_BUILD=1.33); names, descriptions and lore from the D1 manifest
(Bungie's manifest, d1kit/manifest.py), because the game client does not ship that text.
  - Item definition tag 80801806 (012e on 1.01, 0131/0132 on 1.33), keyed by item hash @ITEM_HASH_OFF, holds raw
    "investment" stats as (stat index, value) pairs in an array of class 8080190c.
  - Stat index -> stat hash: investment_globals_012c #92 (class 808017ec), 0x10-byte elements, hash first.
  - Displayed value = the item's StatGroup interpolation of the raw value (what the game UI shows).
"""

import json
import os
import struct
import sys

from d1kit.config import BUILD, ITEM_HASH_OFF, manifest_file
from d1kit.pkg.store import class_entries, table

_cache = {}


def _db(name):
    if name not in _cache:
        _cache[name] = json.load(open(manifest_file(name), encoding="utf-8"))
    return _cache[name]


def _defs():
    if "defs" not in _cache:
        defs = {}
        for p, e in class_entries(0x80801806):
            d = p.read_entry(e["index"])
            defs[struct.unpack_from("<I", d, ITEM_HASH_OFF)[0]] = d
        _cache["defs"] = defs
    return _cache["defs"]


def _stat_hashes():
    if "stat_hashes" not in _cache:
        d = table(92)
        (n,) = struct.unpack_from("<Q", d, 0x20)
        _cache["stat_hashes"] = [struct.unpack_from("<I", d, 0x30 + i * 0x10)[0] for i in range(n)]
    return _cache["stat_hashes"]


def disc_stats(item_hash):
    """[(stat hash, raw value)] from the v1.01 item definition."""
    d = _defs().get(item_hash)
    if d is None:
        return []
    for o in range(0, len(d) - 16, 8):
        if struct.unpack_from("<I", d, o + 8)[0] == 0x8080190C:
            (n,) = struct.unpack_from("<Q", d, o)
            pairs = [struct.unpack_from("<II", d, o + 0x10 + i * 8) for i in range(n)]
            table = _stat_hashes()
            return [(table[i], v) for i, v in pairs if i < len(table)]
    return []


def _table(idx):
    if ("table", idx) not in _cache:
        _cache[("table", idx)] = table(idx)
    return _cache[("table", idx)]


def _display_icon(stub):
    """t128 display stub -> display tag (u32 @0x14) -> first texture tag it references."""
    from d1kit.pkg.tags import entry, read, tags_in

    try:
        disp = struct.unpack_from("<I", read(stub), 0x14)[0]
        for _, c in tags_in(read(disp)):
            if entry(c)[1]["type"] == 32:
                return c
    except Exception:
        return None
    return None


def perk_icon_tag(perk_hash):
    """Disc icon for a sandbox perk: perk list 012c #101 -> perk definition #44.
    1.01: 0x30-byte records, stub @+0x20. 1.33: 0x10-byte entries whose relative pointer @+8 leads to a shared
    0x28-byte display record, stub @+0x18."""
    hashes = _table(101)
    (n,) = struct.unpack_from("<Q", hashes, 0x20)
    for i in range(n):
        if struct.unpack_from("<I", hashes, 0x30 + i * 8)[0] == perk_hash:
            t = _table(44)
            if BUILD == "1.01":
                stub = struct.unpack_from("<I", t, 0x30 + i * 0x30 + 0x20)[0]
            else:
                ptr = 0x30 + i * 0x10 + 8
                stub = struct.unpack_from("<I", t, ptr + struct.unpack_from("<Q", t, ptr)[0] + 0x18)[0]
            return _display_icon(stub) if stub >> 16 >= 0x8080 else None
    return None


def item_icon_tag(item_hash):
    """Disc icon for an item: item list 012c #81 (0x18 stride) -> #26 (0x10 stride, tag @+8) -> stub @0x30."""
    from d1kit.pkg.tags import entry, read, tags_in

    items = _table(81)
    (n,) = struct.unpack_from("<Q", items, 0x20)
    for i in range(n):
        if struct.unpack_from("<I", items, 0x30 + i * 0x18)[0] == item_hash:
            disp = struct.unpack_from("<I", _table(26), 0x30 + i * 0x10 + 8)[0]
            # display stub: @0x30 on 1.01, @0x60 on 1.33 (layout grew) -> first type-128 tag that yields an icon
            for _, t in tags_in(read(disp)):
                if entry(t)[1]["type"] == 128 and _display_icon(t):
                    return _display_icon(t)
            return None
    return None


def disc_stat_group(group_hash):
    """Stat group curves from the disc: investment_globals_012c #35 (class 808033c3), 0x38-byte groups
    (hash @0, scaled-stat array @0x10, maximum @0x30); scaled stats are 0x18-byte records
    (stat index | 0x100 = shown as a number, curve array of (value, weight) u32 pairs).
    Returns None when the group is not on the disc."""
    t = _table(35)
    (n,) = struct.unpack_from("<Q", t, 0x20)
    table = _stat_hashes()
    for i in range(n):
        g = 0x30 + i * 0x38
        if struct.unpack_from("<I", t, g)[0] != group_hash:
            continue
        cnt, rel = struct.unpack_from("<QQ", t, g + 0x10)
        (maximum,) = struct.unpack_from("<I", t, g + 0x30)
        recs = g + 0x18 + rel + 0x10
        out = []
        for k in range(cnt):
            r = recs + k * 0x18
            (stat,) = struct.unpack_from("<I", t, r)
            pc, prel = struct.unpack_from("<QQ", t, r + 8)
            pts = r + 0x10 + prel + 0x10
            curve = [dict(value=v, weight=w) for v, w in (struct.unpack_from("<II", t, pts + j * 8) for j in range(pc))]
            out.append(
                dict(
                    statHash=table[stat & 0xFF],
                    displayAsNumeric=bool(stat & 0x100),
                    displayInterpolation=curve,
                    maximumValue=maximum or 100,
                )
            )
        return out
    return None


def disc_perk_hashes():
    """All sandbox perk hashes present in v1.01 (012c #101)."""
    if "disc_perks" not in _cache:
        t = _table(101)
        (n,) = struct.unpack_from("<Q", t, 0x20)
        _cache["disc_perks"] = {struct.unpack_from("<I", t, 0x30 + i * 8)[0] for i in range(n)}
    return _cache["disc_perks"]


def interpolate(raw, curve):
    pts = sorted((p["value"], p["weight"]) for p in curve)
    if not pts:
        return raw
    if raw <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if raw <= x1:
            return y0 + (y1 - y0) * (raw - x0) / (x1 - x0)
    return pts[-1][1]


def weapon_stats(item):
    """Displayed stats in the game's UI order (StatGroup), plus the archive's value for comparison."""
    stats = _db("Stat")
    # group id comes from the manifest (the item -> group link isn't located on the disc); curves from the disc
    scaled = disc_stat_group(item.get("statGroupHash"))
    curves_from = "disc"
    if scaled is None:
        scaled = _db("StatGroup").get(str(item.get("statGroupHash")), {}).get("scaledStats", [])
        curves_from = "api"
    group = dict(scaledStats=scaled)
    raw = dict(disc_stats(item["itemHash"]))
    archived = item.get("stats", {})
    out = []
    for sc in group.get("scaledStats", []):
        sh = sc["statHash"]
        s = stats.get(str(sh), {})
        if sh not in raw and str(sh) not in archived:
            continue
        disc = round(interpolate(raw[sh], sc["displayInterpolation"])) if sh in raw else None
        out.append(
            dict(
                name=s.get("statName", str(sh)),
                value=disc,
                raw=raw.get(sh),
                archived=archived.get(str(sh), {}).get("value"),
                max=sc.get("maximumValue", 100),
                numeric=sc.get("displayAsNumeric", False),
                description=s.get("statDescription", ""),
                curves=curves_from,
            )
        )
    for o in out:
        o["hidden"] = False
    # hidden stats (not in the UI's stat group): the game and manifest use the raw value directly
    shown = {sc["statHash"] for sc in group.get("scaledStats", [])}
    for sh, v in raw.items():
        s = stats.get(str(sh), {})
        # Light/Attack come from item level and upgrades, not from the investment stats (raw value is 0)
        if sh in shown or not s.get("statName") or s["statName"] in ("Light", "Attack"):
            continue
        out.append(
            dict(
                name=s["statName"],
                value=v,
                raw=v,
                archived=archived.get(str(sh), {}).get("value"),
                max=100,
                numeric=True,
                hidden=True,
                description=s.get("statDescription", ""),
            )
        )
    return out


def _common_perk_names():
    """Perk names found on any non-exotic weapon; anything else on an exotic is its exotic perk."""
    if "common_perks" not in _cache:
        names = set()
        grids = _db("TalentGrid")
        for it in _db("InventoryItem").values():
            if it.get("itemType") != 3 or it.get("tierType") == 6:
                continue
            for n in grids.get(str(it.get("talentGridHash")), {}).get("nodes", []):
                names.update(st.get("nodeStepName") for st in n.get("steps", []))
        _cache["common_perks"] = names
    return _cache["common_perks"]


def weapon_perks(item):
    """Talent grid nodes by column: [{column, perks: [{name, description, icon, exotic}]}]."""
    grid = _db("TalentGrid").get(str(item.get("talentGridHash")), {})
    common = _common_perk_names()
    cols = {}
    for n in grid.get("nodes", []):
        steps = []
        for st in n.get("steps", []):
            name = st.get("nodeStepName") or ""
            if not name or name.startswith("Upgrade") or name == "Ascend":
                continue
            perk_hashes = st.get("perkHashes") or []
            steps.append(
                dict(
                    name=name,
                    description=_clean(st.get("nodeStepDescription") or ""),
                    icon=st.get("icon"),
                    exotic=name not in common,
                    # a perk whose hash isn't in v1.01's perk list was added after launch
                    # (damage-type nodes are not sandbox perks, so they're never flagged)
                    in_v101=(
                        not perk_hashes or name.endswith(" Damage") or any(h in disc_perk_hashes() for h in perk_hashes)
                    ),
                    icon_tag=next((t for t in map(perk_icon_tag, perk_hashes) if t), None),
                )
            )
        if steps:
            cols.setdefault(n["column"], []).extend([dict(s, row=n["row"]) for s in steps])
    out = []
    for c in sorted(cols):
        uniq, seen = [], set()
        for s in sorted(cols[c], key=lambda x: x["row"]):
            if s["name"] not in seen:
                seen.add(s["name"])
                uniq.append(s)
        out.append(dict(column=c, perks=uniq))
    return out


def _clean(text):
    """Manifest text -> plain text paragraphs (drop markup, decode entities, fix the broken dash glyph)."""
    import html
    import re

    t = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("�", " - ").replace("\r", "")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def lore(item):
    """Flavour text plus any Grimoire card named after the weapon."""
    cards = []
    name = (item.get("itemName") or "").lower()
    for c in _db("GrimoireCard").values() if os.path.exists(manifest_file("GrimoireCard")) else []:
        if (c.get("cardName") or "").lower() == name:
            cards.append(
                dict(title=c.get("cardName"), intro=_clean(c.get("cardIntro")), text=_clean(c.get("cardDescription")))
            )
    return dict(flavor=_clean(item.get("itemDescription")), cards=cards)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from d1kit.game.gear import find_item

    for n in sys.argv[1:]:
        it = find_item(n)
        print("==", it["itemName"])
        for s in weapon_stats(it):
            print(f"  {s['name']:<18} disc={s['value']!s:>5} (raw {s['raw']!s:>4})  archive={s['archived']}")
        for c in weapon_perks(it):
            print(f"  col {c['column']}: {[p['name'] for p in c['perks']]}")
        print("  lore:", lore(it))
