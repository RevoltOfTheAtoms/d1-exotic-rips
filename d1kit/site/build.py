"""Build the viewer site: copy each exported GLB, make atlas thumbnails, and inline the weapon data into index.html.

    exports (EXPORT_DIR/<slug>/)  +  viewer sources (FRONTEND_DIR)  ->  SITE_DIR (static files, serve anywhere)

Weapon text (names, perks, lore) comes from Bungie's manifest; icons from the disc first, bungie.net as a fallback.
"""

import json
import os
import shutil
import struct
import time
import urllib.request

from PIL import Image

from d1kit.config import BUILD, EXPORT_DIR, FRONTEND_DIR, SITE_DIR
from d1kit.game.gear import arrangement, find_item, items
from d1kit.game.items import item_icon_tag, lore, weapon_perks, weapon_stats
from d1kit.pkg.store import table
from d1kit.textures.decode import extract

TEMPLATE = os.path.join(FRONTEND_DIR, "template.html")
# viewer files copied as they are: the game-lighting module, the QA contact sheet, and the images ripped by
# `d1rip.py setup` (site/viewer_assets.py)
SHARED_FILES = ("d1light.js", "sheet.html", "inspect_bg.png", "env_80a7451f.png", "env_80a0856c.png")
ICONS = os.path.join(SITE_DIR, "icons")
_icon_ok = {}

# version-specific labels and the "where does each value come from" table shown on the site
V = BUILD
INFO = {
    "1.01": dict(
        label="Destiny 1 · PS4 disc v1.01 · CUSA00568",
        manifest="API · Bungie manifest (2016)",
        manifestShort="2016",
        manifestDesc="an archived copy of that manifest (destiny-db, Nov 2016)",
        perkNote="they were added or reworked after launch.",
    ),
    "1.33": dict(
        label="Destiny 1 · PS4 v1.33 (disc + final patch) · CUSA00568",
        manifest="API · Bungie final D1 manifest",
        manifestShort="final",
        manifestDesc="Bungie's final D1 manifest (mirrored by cryptarch-guide), which "
        "matches 1.33's 8,609 item definitions one for one",
        perkNote="the perk exists only as text in the manifest, not as a sandbox perk in the game files.",
    ),
}[V]
INFO.update(
    ver=V,
    exportDir=os.path.basename(EXPORT_DIR),
    sources=[
        ["3D models, textures, shaders", "disc", f"Only the game files have the geometry and textures (v{V})."],
        ["Which parts make up each gun", "disc", f"The v{V} gear-art tables."],
        [
            "Dyes: which ones, colours, names",
            "disc",
            "Each weapon's definition lists its dyes; the dye files hold the colours.",
        ],
        [
            "Dye blend formula",
            "web",
            "Bungie's D1 web gear viewer code; the game's own version is compiled PS4 shader code.",
        ],
        [
            "Stat numbers and display curves",
            "disc",
            f"v{V} values; a weapon whose stat group isn't in the files falls back to API curves.",
        ],
        [
            "Which stat group a weapon uses",
            "api",
            "The weapon-to-group link isn't found in the files yet; the curves themselves are disc.",
        ],
        ["Tier (Exotic, Legendary, ...)", "disc", "A byte in each item definition."],
        [
            "Weapon and perk icons",
            "disc",
            "Traced through the item and perk tables. Bungie's server no longer has D1 perk icons.",
        ],
        [
            "Talent grid layout",
            "api",
            f"The grid format isn't decoded yet. Every perk is checked against the v{V} perk list.",
        ],
        [
            "Year 1 / reissue label",
            "api",
            "Same-named copies are told apart by the manifest's item level (20 = Year 1).",
        ],
        [
            "Names, types, descriptions, lore",
            "api",
            "Not in the game files (all packages and eboot scanned): "
            "Destiny downloads this text from Bungie at sign-in.",
        ],
    ],
)


def fetch_icon(path):
    """Download a bungie.net icon path once into the site's icons/; returns the site-relative path or None (gone)."""
    if not path or "missing_icon" in path:
        return None
    if path in _icon_ok:
        return _icon_ok[path]
    name = os.path.basename(path)
    dst = os.path.join(ICONS, name)
    if not os.path.exists(dst) and not os.path.exists(dst + ".missing"):
        os.makedirs(ICONS, exist_ok=True)
        try:
            with urllib.request.urlopen("https://www.bungie.net" + path, timeout=30) as r:
                data = r.read()
            with open(dst, "wb") as f:
                f.write(data)
        except Exception:
            open(dst + ".missing", "w").close()
    _icon_ok[path] = f"icons/{name}" if os.path.exists(dst) else None
    return _icon_ok[path]


def disc_icon(tag):
    """Decode an icon texture from the disc into the site's icons/; returns the site-relative path or None."""
    if not tag:
        return None
    rel = f"icons/disc_{tag:08x}.png"
    dst = os.path.join(SITE_DIR, rel)
    if not os.path.exists(dst):
        os.makedirs(ICONS, exist_ok=True)
        try:
            img, _ = extract(tag)
            img.convert("RGBA").save(dst)
        except Exception:
            return None
    return rel


def test_item_twins():
    """slot-1 asset -> names of Bungie's internal test items ('NAME~') that use it, from the disc arrangements."""
    t = table(96)
    (n,) = struct.unpack_from("<Q", t, 0x20)
    twins = {}
    for i, h in enumerate(struct.unpack_from(f"<{n}I", t, 0x30)):
        name = (items().get(str(h)) or {}).get("itemName") or ""
        if name.endswith("~"):
            for a in arrangement(i).get(1, [])[:1]:
                twins.setdefault(a, []).append(name)
    return twins


def copy_viewer_files():
    os.makedirs(os.path.join(SITE_DIR, "atlas"), exist_ok=True)
    for f in SHARED_FILES:
        shutil.copy(os.path.join(FRONTEND_DIR, f), os.path.join(SITE_DIR, f))
    # three.js (MIT) and the UI fonts (SIL OFL), bundled so the site needs no CDN
    shutil.copytree(os.path.join(FRONTEND_DIR, "vendor"), os.path.join(SITE_DIR, "vendor"), dirs_exist_ok=True)


def exported_slugs():
    """Every weapon in the export folder, by type then name (unreleased items, which have no type, last)."""
    found = []
    for d in os.listdir(EXPORT_DIR):
        rp = os.path.join(EXPORT_DIR, d, "export_report.json")
        if os.path.exists(rp):
            with open(rp) as f:
                r = json.load(f)
            if not r["parts"]:  # gear art with no parts on this build (e.g. Necrochasm on 1.01)
                continue
            found.append((r["type"] is None, r["type"] or "", r["item"], d))
    return [f[-1] for f in sorted(found)]


def weapon_entry(slug, twins):
    """Copy one export into the site and return its record for the page."""
    src = os.path.join(EXPORT_DIR, slug)
    with open(os.path.join(src, "export_report.json")) as f:
        rep = json.load(f)
    shutil.copy(os.path.join(src, f"{slug}.glb"), os.path.join(SITE_DIR, f"{slug}.glb"))
    atlases = []
    for canvas in sorted(rep["canvases"], key=int):
        row = {"canvas": int(canvas), "size": rep["canvases"][canvas]["size"], "maps": {}}
        for kind in ("diffuse", "normal", "gearstack"):
            im = Image.open(os.path.join(src, "textures", "atlas", f"canvas{canvas}_{kind}.png")).convert("RGB")
            im.thumbnail((384, 384))
            name = f"atlas/{slug}_c{canvas}_{kind}.jpg"
            im.save(os.path.join(SITE_DIR, name), quality=85)
            row["maps"][kind] = name
        atlases.append(row)
    item = find_item(str(rep["itemHash"]))
    # disc quirk: some items point at a Bungie test item's model ('NAME~'), so the model won't match the icon
    slot1 = next((p["asset"] for p in rep["parts"] if p["slot"] == 1), None)
    twin = twins.get(int(slot1, 16)) if slot1 else None
    note = (
        f"The game files map this item to the same model parts as Bungie's internal test item "
        f"{twin[0]}, so the model doesn't match the item's icon. The export follows the files as they are."
        if twin
        else None
    )
    if rep.get("art_note"):  # the export used other art (see gear.art_index_for / gear.shared_raid_art)
        note = (
            "The game files point this reissue at art that belongs to another item ("
            + rep["art_note"].split("; ")[0].replace("disc art is shared with ", "")
            + "). Bungie's own gear data shows it with the Year 1 model, so that model is used here."
        )
    # Year 1 vs reissue, only for names that occur more than once
    same = [v for v in items().values() if v.get("itemName") == item.get("itemName") and v.get("itemType") == 3]
    edition = None
    if V != "1.01" and len(same) > 1 and item.get("itemName"):
        edition = "Year 1" if item.get("itemLevels") == [20] else "Reissue"
    # icons: disc first, bungie.net only as a fallback
    perks = weapon_perks(item)
    for col in perks:
        for p in col["perks"]:
            p["icon"] = disc_icon(p.pop("icon_tag", None)) or fetch_icon(p.get("icon"))
    icon = disc_icon(item_icon_tag(item["itemHash"])) or fetch_icon(item.get("icon"))
    return dict(
        stats=weapon_stats(item),
        perks=perks,
        lore=lore(item),
        icon=icon,
        tier=rep.get("tier") or item.get("tierTypeName"),
        edition=edition,
        note=note,
        damage=item.get("damageTypes", []),
        slug=slug,
        name=rep["item"],
        type=rep["type"] or "Unreleased",
        hash=rep["itemHash"],
        gearArt=rep["gearArtArrangementIndex"],
        parts=rep["parts"],
        atlases=atlases,
        materials=len(rep["materials"]),
        dyes=[
            dict(
                slot=int(s),
                name=(d["source"] or "").split("\\")[-1].replace(".gear_dye.tft", ""),
                primary=d["primary"][:3],
                secondary=d["secondary"][:3],
            )
            for s, d in sorted(rep.get("dyes", {}).items())
        ],
        shaders=sum(len(m["shaders"]) for m in rep["materials"].values()),
        glbBytes=os.path.getsize(os.path.join(SITE_DIR, f"{slug}.glb")),
    )


def build_site(slugs=None):
    """Build SITE_DIR from the exports (all of them, or just `slugs`)."""
    copy_viewer_files()
    twins = test_item_twins() if BUILD != "1.01" else {}
    weapons = [weapon_entry(slug, twins) for slug in (slugs or exported_slugs())]
    stamp = str(int(time.time()))  # cache-bust the shared module: simple static servers send no cache headers
    with open(TEMPLATE, encoding="utf-8") as f:
        html = (
            f.read()
            .replace('"./d1light.js"', f'"./d1light.js?v={stamp}"')
            .replace("/*__WEAPONS__*/[]", json.dumps(weapons))
            .replace("/*__BUILD__*/{}", json.dumps(INFO))
        )
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"built {len(weapons)} weapons into {SITE_DIR}")
    return weapons
