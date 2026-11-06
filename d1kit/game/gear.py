"""D1 v1.01 gear lookups: item -> gear-art arrangement -> part asset hashes -> entity/mesh/plate tags."""

import collections
import json
import struct

from d1kit.config import BUILD, ITEM_HASH_OFF, manifest_file
from d1kit.pkg.store import table
from d1kit.pkg.tags import asset_lookup, entry, read, tags_in

CLS_ENTITY = 0x80800734
CLS_MESH = 0x80801AB5
CLS_PLATESET = 0x80801C3C
CLS_PLATE = 0x80800147
CLS_MATERIAL = 0x80801AD7

_items = None
_arr = None


def items():
    global _items
    if _items is None:
        _items = json.load(open(manifest_file("InventoryItem"), encoding="utf-8"))
    return _items


def find_item(name_or_hash):
    it = items()
    if str(name_or_hash) in it:
        return it[str(name_or_hash)]
    if str(name_or_hash).isdigit() and gear_art_index(int(name_or_hash)) is not None:
        return {"itemHash": int(name_or_hash)}  # on disc but not in the manifest (never-released item)
    hits = [
        v
        for v in it.values()
        if (v.get("itemName") or "").lower() == str(name_or_hash).lower() and v.get("itemType") == 3
    ]
    # same name on several items (Year 1 / Year 2 copies): the first with gear art on this build
    hits.sort(key=lambda v: (gear_art_index(v["itemHash"]) is None, gear_art_index(v["itemHash"]) or 0))
    return hits[0] if hits else None


def item_name(item):
    """Manifest name; Bungie never named a few unreleased items ('' or 'Classified')."""
    n = (item.get("itemName") or "").strip()
    return n if n and n != "Classified" else f"Unreleased {item.get('itemTypeName') or 'item'} {item['itemHash']}"


TIERS = {0: "Basic", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Legendary", 5: "Exotic"}


def disc_tier(item_hash):
    """Tier name from the item definition on disc (byte @ITEM_HASH_OFF+0x12, 1.33 checked: value + 1 = tierType)."""
    from d1kit.game.items import _defs

    d = _defs().get(item_hash)
    if d is None:
        return None
    return TIERS.get(d[ITEM_HASH_OFF + 0x12])


_art_index = None


def gear_art_index(item_hash):
    """v1.01 arrangement index for an item: investment_globals_012c #40's sibling table #96 (class 808016fe)
    lists one item hash per arrangement. The archived (2016) manifest's gearArtArrangementIndex is shifted by
    later content and must not be used for v1.01."""
    global _art_index
    if _art_index is None:
        t = table(96)
        (n,) = struct.unpack_from("<Q", t, 0x20)
        _art_index = {h: i for i, h in enumerate(struct.unpack_from(f"<{n}I", t, 0x30))}
    return _art_index.get(item_hash)


_art_owners = None


def art_index_for(item_hash):
    """Arrangement index to render an item with, and a note when it differs from the disc's own.

    On 1.33 a few Rise of Iron reissues point at art that belongs to another item: the Gjallarhorn reissue at Iron
    Gjallarhorn's, Thorn's reissue at a 'FEVER AND REMEDY~' test item's. Bungie's web gear data (and the game) show
    them with the Year 1 model, so when an item's art is shared with a differently named or test item and a
    same-named item has art of its own, that one is used."""
    global _art_owners
    idx = gear_art_index(item_hash)
    if idx is None and BUILD != "1.01":
        return shared_raid_art(item_hash)
    if idx is None or BUILD == "1.01":
        return idx, None
    t = table(96)
    (n,) = struct.unpack_from("<Q", t, 0x20)
    hs = struct.unpack_from(f"<{n}I", t, 0x30)
    names = {int(k): (v.get("itemName") or "") for k, v in items().items()} if isinstance(items(), dict) else {}
    if _art_owners is None:
        _art_owners = collections.defaultdict(list)
        for i, h in enumerate(hs):
            a = arrangement(i).get(1, [])[:1]
            if a:
                _art_owners[a[0]].append(h)
    mine = arrangement(idx).get(1, [])[:1]
    name = names.get(item_hash, "")
    if not mine or not name:
        return idx, None
    sharers = [h for h in _art_owners[mine[0]] if h != item_hash]
    if not any(names.get(h, "") != name for h in sharers):
        return idx, None
    for i, h in enumerate(hs):
        if h != item_hash and names.get(h) == name:
            a = arrangement(i).get(1, [])[:1]
            if a and not any(names.get(o, "") != name for o in _art_owners[a[0]] if o != h):
                return (
                    i,
                    f"disc art is shared with {', '.join(sorted({names.get(o) or str(o) for o in sharers}))}; "
                    f"using the {name} art of item {h}",
                )
    return idx, None


def shared_raid_art(item_hash):
    """Exotic-tier raid weapons with no arrangement of their own on 1.33 (the Age of Triumph '(Adept)' items and the
    Wrath of the Machine '((NAME~))' items) use the model of the same-named raid weapon that has one in table #96
    (e.g. 'Fatebringer (Adept)' -> 'Fatebringer'). Returns (index, note) or (None, None)."""
    if not isinstance(items(), dict):
        return None, None
    name = (items().get(str(item_hash), {}).get("itemName") or "").strip()
    base = name[: -len(" (Adept)")] if name.endswith(" (Adept)") else name
    if base.startswith("((") and base.endswith("))"):
        base = base[2:-2]
    if not base or base == name and not name.endswith(")"):
        return None, None
    t = table(96)
    (n,) = struct.unpack_from("<Q", t, 0x20)
    for i, h in enumerate(struct.unpack_from(f"<{n}I", t, 0x30)):
        if h != item_hash and (items().get(str(h), {}).get("itemName") or "").strip() == base:
            return i, f"no gear art of its own; uses the model of {base} (item {h})"
    return None, None


def arrangement(index):
    """Gear-art arrangement table: investment_globals_012c #40 (class 808034d7), 0x18-byte elements.
    Returns {slot id: [asset hashes]}."""
    global _arr
    if _arr is None:
        _arr = table(40)
    d = _arr
    o = 0x30 + index * 0x18
    _, cnt, rel = struct.unpack_from("<QQQ", d, o)
    slots = collections.OrderedDict()
    if not cnt:
        return slots
    # header [count][class] then elements: 1.01 inline 0x18-byte records (slot, count, rel);
    # 1.33 u64 relative pointers to shared records of the same shape
    t = o + 0x10 + rel + 0x10
    for i in range(cnt):
        if BUILD == "1.01":
            eo = t + i * 0x18
        else:
            p = t + i * 8
            eo = p + struct.unpack_from("<Q", d, p)[0]
        slot, n, r = struct.unpack_from("<QQQ", d, eo)
        lst = eo + 0x10 + r + 0x10
        slots[slot] = list(struct.unpack_from(f"<{n}I", d, lst)) if n else []
    return slots


def part_entity(asset_hash):
    stub = asset_lookup(asset_hash)
    if stub is None:
        return None
    p, e = entry(stub)
    if e["type"] == 128:  # 24-byte stub pointing at the entity (stub + 1)
        stub = struct.unpack_from("<I", read(stub), 0x10)[0]
    return stub


def collect(root, classes, maxdepth=4):
    """BFS over tag references from root; returns {class: [tags]} for the requested classes."""
    found = collections.defaultdict(list)
    seen, frontier = {root}, [root]
    for _ in range(maxdepth):
        nxt = []
        for t in frontier:
            p, e = entry(t)
            if e["type"] != 16:
                continue
            if e["reference"] in classes and t not in found[e["reference"]]:
                found[e["reference"]].append(t)
            if e["reference"] == CLS_MATERIAL:
                continue  # don't wander into shared shader globals
            for _, c in tags_in(read(t)):
                if c not in seen:
                    seen.add(c)
                    nxt.append(c)
        frontier = nxt
    for t in frontier:
        p, e = entry(t)
        if e["type"] == 16 and e["reference"] in classes and t not in found[e["reference"]]:
            found[e["reference"]].append(t)
    return found


def parse_mesh_tag(t):
    """80801ab5: mesh array (80801bbf, 0xA0 stride) each with buffers and part list (80801aef, 0x24 stride)."""
    d = read(t)
    n, rel = struct.unpack_from("<QQ", d, 0x10)
    base = 0x18 + rel + 0x10
    meshes = []
    for i in range(n):
        m = base + i * 0xA0
        f = struct.unpack_from("<12f", d, m)
        vbs = struct.unpack_from("<4I", d, m + 0x30)
        (ib,) = struct.unpack_from("<I", d, m + 0x40)
        pc, prel = struct.unpack_from("<QQ", d, m + 0x48)
        pb = m + 0x50 + prel + 0x10
        parts = []
        for j in range(pc):
            po = pb + j * 0x24
            mat, u1, start, count, u4, u5, u6, flags, u8 = struct.unpack_from("<9I", d, po)
            parts.append(
                dict(
                    material=mat,
                    start=start,
                    count=count,
                    flags=flags,
                    lod=flags >> 24,
                    cci=(flags >> 16) & 0xFF,
                    u1=u1,
                    u4=u4,
                    u5=u5,
                    u6=u6,
                    u8=u8,
                )
            )  # cci: dye slot*2 + secondary
        meshes.append(
            dict(
                pos_scale=f[0:4],
                pos_offset=f[4:8],
                uv_scale=f[8:10],
                uv_offset=f[10:12],
                vbs=[v for v in vbs if v != 0xFFFFFFFF],
                ib=ib,
                parts=parts,
            )
        )
    return meshes


def parse_plateset(t):
    """80801c3c -> 3 plate tags (80800147): slot, texture tag, rect x,y,w,h."""
    d = read(t)
    plates = []
    for _, c in tags_in(d):
        p, e = entry(c)
        if e["reference"] != CLS_PLATE:
            continue
        pd = read(c)
        (slot,) = struct.unpack_from("<I", pd, 0x08)
        n, rel = struct.unpack_from("<QQ", pd, 0x10)
        b = 0x18 + rel + 0x10
        for i in range(n):
            tex, x, y, w, h = struct.unpack_from("<5I", pd, b + i * 0x14)
            plates.append(dict(slot=slot, texture=tex, x=x, y=y, w=w, h=h))
    return plates
