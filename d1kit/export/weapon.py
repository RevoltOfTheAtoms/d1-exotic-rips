"""Export one weapon from the dump: GLB model + raw textures, shaders and material data + a JSON report.

Pipeline (read-only on the dump):
    item -> gear-art arrangement (investment table #40) -> part asset hashes per gear slot
    -> entity -> mesh tags + plate sets
    -> geometry (mesh.py), each draw classified as plated canvas surface or special (specials.py)
    -> canvas atlases: plates composited, dyed, baked with the game's shaders (canvas.py)
    -> glTF materials + GLB (gltf.py); the per-weapon exceptions are in overrides.py
"""

import collections
import json
import os
import re

import numpy as np

from d1kit.config import BUILD, EXPORT_DIR
from d1kit.export import gltf
from d1kit.export.canvas import bake_canvas, canvas_size, on_plates
from d1kit.export.materials import LENS_PS, PASS_MATERIALS, cached_info, material_info
from d1kit.export.mesh import decode_mesh, primitive, triangles
from d1kit.export.overrides import SKIP_MATERIALS, SWORD_FX
from d1kit.export.specials import glow_effect, special_material, sword_effect
from d1kit.game.dyes import FORCE_DYE, item_dyes
from d1kit.game.gear import (
    CLS_MESH,
    CLS_PLATESET,
    arrangement,
    art_index_for,
    collect,
    disc_tier,
    find_item,
    item_name,
    parse_mesh_tag,
    parse_plateset,
    part_entity,
)
from d1kit.pkg.tags import entry, read
from d1kit.textures.decode import extract

UNUSED_SLOT = 0x811C9DC5  # FNV-1a of an empty string: the arrangement slot is unused

# part flags
FLAG_EFFECT = 0x20  # translucent / additive effect pass (glows, smoke, holo reticles, sword energy)
FLAG_DECAL = 0x40  # decal layer (e.g. SUROS Regime's livery)
FLAG_RENDER_TARGET = 0x300  # scope lens / screen showing a runtime render target
FLAG_CRYSTAL = 0x10  # sword hilt crystal, tinted by the element colour


def slug_for(it):
    name = item_name(it)
    slug = re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_").replace("-", "_"))
    if BUILD != "1.01":  # Year 1 / Year 2 copies share names on 1.33
        slug = f"{slug}_{it['itemHash']}"
    return slug


def collect_parts(ga):
    """The weapon's parts: one per used gear slot (first variant), with its mesh and plate-set tags."""
    parts = []
    for slot, hashes in arrangement(ga).items():
        if not hashes or hashes[0] == UNUSED_SLOT:
            continue
        h = hashes[0]
        ent = part_entity(h)
        if ent is None:
            print(f"   slot {slot}: asset {h:08x} not on disc")
            continue
        found = collect(ent, {CLS_MESH, CLS_PLATESET})
        parts.append(
            dict(
                slot=slot,
                asset=h,
                entity=ent,
                meshes=found[CLS_MESH],
                platesets=found[CLS_PLATESET],
                variants=len(hashes),
            )
        )
    return parts


def assign_canvases(parts):
    """canvas -> [(part index, channel, plate)]; also sets each part's canvas and its plate rectangles (0..1 UV)."""
    canvases = collections.defaultdict(list)
    for pi, p in enumerate(parts):
        p["canvas"] = None
        for ps in p["platesets"]:
            for pl in parse_plateset(ps):
                canvas, ch = pl["slot"] >> 16, pl["slot"] & 0xFFFF
                canvases[canvas].append((pi, ch, pl))
                p["canvas"] = canvas
    for plates in canvases.values():
        size = canvas_size(plates)
        for pi, _, pl in plates:
            parts[pi].setdefault("plates", []).append(
                (pl["x"] / size, pl["y"] / size, (pl["x"] + pl["w"]) / size, (pl["y"] + pl["h"]) / size)
            )
    for p in parts:
        p.setdefault("plates", [])
    return canvases


class Geometry:
    """Walks every draw of every part and sorts its triangles into primitives keyed by how they're drawn:
    ("canvas", canvas), ("cutout", canvas), ("special", material), ("glass", None), ("untextured", None)."""

    def __init__(self, report, keep_effects, is_sword):
        self.report = report
        self.keep_effects = keep_effects
        self.is_sword = is_sword
        self.nodes = []  # [(node name, [primitive])]
        self.mats_seen = {}  # material -> {gear slots}
        self.uv_tris = collections.defaultdict(list)  # canvas -> [(change colour index, (N,3,2) uvs)]
        self.mat_tris = collections.defaultdict(list)  # canvas -> [(material, (N,3,2) uvs)]
        self.specials = {}  # material -> special dict (or None = plated)

    def add_part(self, p):
        prims = []
        for mt in p["meshes"]:
            for m in parse_mesh_tag(mt):
                prims += self._mesh(p, m)
        self.nodes.append((f"slot{p['slot']}_{p['asset']:08x}", prims))
        info = dict(
            slot=p["slot"],
            asset=f"{p['asset']:08x}",
            entity=f"{p['entity']:08x}",
            variants=p["variants"],
            canvas=p["canvas"],
            meshes=[f"{x:08x}" for x in p["meshes"]],
            triangles=sum(len(x["idx"]) for x in prims),
            vertices=sum(len(x["pos"]) for x in prims),
            special=[f"{x['key'][1]:08x}" for x in prims if x["key"][0] == "special"],
        )
        self.report["parts"].append(info)
        print(
            f"   slot {p['slot']:>2} {p['asset']:08x}: {info['vertices']} verts, {info['triangles']} tris, "
            f"canvas {p['canvas']}, {len(info['special'])} special"
        )

    def _effect_kept(self, p, mat):
        """Effect passes are left out, except plain lights on the gun (glows); logged in the report."""
        if mat not in self.specials:
            g = glow_effect(mat)
            if g is None and self.is_sword and SWORD_FX:
                g = sword_effect(mat)
            if g is not None:
                self.specials[mat] = g
            fx = material_info(mat)
            self.report.setdefault("effects", {})[f"{mat:08x}"] = dict(
                ps=fx["shaders"].get("ps"),
                kept=g is not None,
                slot=p["slot"],
                textures=[t["tag"] for t in fx["textures"]],
                constants=[[round(x, 4) for x in c] for c in fx["constants"][:8]],
            )
        sp = self.specials.get(mat)
        if sp is not None and sp.get("texture") == "effect":
            return True
        self.report["effects_removed"] = self.report.get("effects_removed", 0) + 1
        return False

    def _mesh(self, p, m):
        pos, uv, nrm, ib = decode_mesh(m)
        seen_ranges = set()
        groups = collections.defaultdict(list)
        for part in m["parts"]:
            mat, flags = part["material"], part["flags"]
            if mat in PASS_MATERIALS or not (part["lod"] & 1):
                continue
            if flags & FLAG_EFFECT and not self.keep_effects and not self._effect_kept(p, mat):
                continue
            key = (part["start"], part["count"])
            if key in seen_ranges:  # one material per triangle range (later passes on it aren't drawn)
                continue
            seen_ranges.add(key)
            if mat in SKIP_MATERIALS:  # the range stays claimed, so later passes don't take its place
                self.report.setdefault("skipped_materials", []).append(f"{mat:08x}")
                continue
            self.mats_seen.setdefault(mat, set()).add(p["slot"])
            pt = triangles(ib[part["start"] : part["start"] + part["count"]])
            if not pt:
                continue
            if mat not in self.specials:
                self.specials[mat] = special_material(mat)
            gkey = self._classify(p, part, self.specials[mat], uv, pt)
            if gkey is not None:
                groups[gkey] += pt
        return [primitive(tris, pos, uv, nrm, gkey) for gkey, tris in groups.items()]

    def _classify(self, p, part, sp, uv, pt):
        """How a draw is rendered: a primitive group key, or None to leave it out."""
        mat, flags = part["material"], part["flags"]
        tri_uvs = None if uv is None else uv[np.array(pt)]
        if sp is not None and sp["kind"] == "glass" and flags & FLAG_DECAL:
            # decal layer without its own texture: it samples the gun's plate atlas (e.g. Ace of Spades' spade on
            # the grip, painted in a decal panel of canvas 0). Only when its UVs land on this part's plates;
            # otherwise they belong to a runtime-only texture (e.g. Plan C's sight decal): nothing on disc to draw.
            if tri_uvs is None or p["canvas"] is None or not on_plates(tri_uvs, p["plates"]):
                return None
            # alpha-tested against gearstack B, so only the marking itself is drawn, not the whole decal panel
            return ("cutout", p["canvas"])
        lens_off = False
        if sp is None and not flags & FLAG_RENDER_TARGET and tri_uvs is not None and p["canvas"] is not None:
            # lens shader whose UVs don't land on this part's plates (e.g. MIDA's scope lens 80a720aa: its UVs sweep a
            # disc across canvas 0): baking it into the canvas would paint over the plates, so it is glass too
            if cached_info(mat)["shaders"].get("ps") == LENS_PS and not on_plates(tri_uvs, p["plates"]):
                lens_off = True
                self.report["lens_off_plates"] = sorted(set(self.report.get("lens_off_plates", [])) | {f"{mat:08x}"})
        if sp is None and (flags & FLAG_RENDER_TARGET or lens_off):
            # lens / screen showing a runtime render target; UVs cover that target, not the plates -> glass
            return ("glass", None)
        if sp is not None:
            return ("special", mat)
        if tri_uvs is not None and p["canvas"] is not None:
            # change colour index (dye slot = cci // 2, odd = secondary colour) is byte 2 of the part flags; checked
            # against Bungie's web models (gear_dye_change_color_index)
            cci = (flags >> 16) & 0xFF
            if flags & FLAG_CRYSTAL and cci in (0, 3) and self.is_sword and p["slot"] == 0:
                # swords: the hilt crystal (gear slot 0; slot 1 is the blade) is tinted in game by the element
                # colour, which the sword dye carries as slot 1 secondary (arc blue, solar orange, void purple).
                # It has no dye mask (R) of its own: tint all of it.
                cci = 3 + FORCE_DYE
            self.uv_tris[p["canvas"]].append((cci if cci < 8 or cci >= FORCE_DYE else 0, tri_uvs))
            self.mat_tris[p["canvas"]].append((mat, tri_uvs))
            return ("canvas", p["canvas"])
        return ("untextured", None)


def drop_sword_trails(nodes, specials, report):
    """Sword energy passes: keep the ones hugging the blade (resting glow), drop the swing trail and other cards that
    reach outside the sword's own surface (bounds of the plated geometry, 15% margin)."""
    surf = [pr["pos"] for _, prims in nodes for pr in prims if pr["key"][0] in ("canvas", "cutout")]
    if not surf:
        return
    allp = np.concatenate(surf)
    lo, hi = allp.min(0), allp.max(0)
    pad = (hi - lo) * 0.15 + 0.01
    for ni, (name, prims) in enumerate(nodes):
        keep = []
        for pr in prims:
            sp = specials.get(pr["key"][1]) if pr["key"][0] == "special" else None
            outside = np.any(pr["pos"].min(0) < lo - pad) or np.any(pr["pos"].max(0) > hi + pad)
            if sp and sp.get("sword") and outside:
                report["sword_fx_dropped"] = report.get("sword_fx_dropped", []) + [f"{pr['key'][1]:08x}"]
                continue
            keep.append(pr)
        nodes[ni] = (name, keep)


def save_material_data(out, mats_seen, report):
    """Every used material's shaders (GCN binaries + headers), textures and parameters, for reference."""
    for mt, slots in mats_seen.items():
        mi = material_info(mt)
        mi["used_by_slots"] = sorted(slots)
        for stage, st in mi["shaders"].items():
            _, e = entry(int(st, 16))
            with open(os.path.join(out, "shaders", f"{mt:08x}_{stage}_{st}.gcn.bin"), "wb") as f:
                f.write(read(e["reference"]))
            with open(os.path.join(out, "shaders", f"{mt:08x}_{stage}_{st}.header.bin"), "wb") as f:
                f.write(read(int(st, 16)))
        for t in mi["textures"]:
            try:
                extract(
                    int(t["tag"], 16), os.path.join(out, "textures", "material", f"{mt:08x}_slot{t['slot']}_{t['tag']}")
                )
            except Exception as ex:  # cubemaps / unknown formats: keep raw
                t["note"] = str(ex)
        report["materials"][f"{mt:08x}"] = mi
        with open(os.path.join(out, "materials", f"{mt:08x}.json"), "w", newline="\n") as f:
            json.dump(mi, f, indent=1)


def export(name, out_root=EXPORT_DIR, preview_size=1024, keep_effects=False):
    """Export a weapon by item name or hash into out_root/<slug>/. Returns that folder.
    keep_effects: also keep translucent effect passes (smoke, holo reticles, ...) that are normally left out."""
    it = find_item(name)
    if not it:
        raise SystemExit(f"item not found: {name}")
    ga, art_note = art_index_for(it["itemHash"])
    if ga is None:
        raise SystemExit(f"{it['itemName']} has no gear art in v{BUILD}")
    name, slug = item_name(it), slug_for(it)
    out = os.path.join(out_root, slug)
    for sub in ("textures/parts", "textures/atlas", "shaders", "materials"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    report = dict(
        item=name,
        itemHash=it["itemHash"],
        type=it.get("itemTypeName"),
        build=BUILD,
        tier=disc_tier(it["itemHash"]),
        slug=slug,
        gearArtArrangementIndex=ga,
        parts=[],
        canvases={},
        materials={},
    )
    if art_note:
        report["art_note"] = art_note
    print(f"== {name} ({it['itemHash']}) gearArt {ga}")

    parts = collect_parts(ga)
    canvases = assign_canvases(parts)

    # geometry first, so dye regions and materials can be rasterised per canvas
    geo = Geometry(report, keep_effects, is_sword=(it.get("itemTypeName") or "") == "Sword")
    for p in parts:
        geo.add_part(p)

    item_dye = item_dyes(it)
    report["dyes"] = {
        s: {k: v for k, v in d.items() if k not in ("detail_diffuse", "detail_normal")}
        | dict(detail_diffuse=f"{d['detail_diffuse']:08x}", detail_normal=f"{d['detail_normal']:08x}")
        for s, d in item_dye.items()
    }
    print(f"   dyes: {[(s, (d['source'] or '').split(chr(92))[-1]) for s, d in item_dye.items()]}")

    # canvases -> atlas images + materials
    images, materials = [], []
    canvas_mat, cutouts = {}, {}
    caches = dict(detail={}, shine={})
    for canvas, plates in sorted(canvases.items()):
        c = bake_canvas(
            canvas,
            plates,
            parts,
            geo.uv_tris[canvas],
            geo.mat_tris[canvas],
            item_dye,
            caches,
            out,
            preview_size,
            report.setdefault("shader_bake", {}),
        )
        report["canvases"][canvas] = dict(size=c["size"], plates=len(plates))
        base = len(images)
        images += c["images"]
        materials.append(gltf.canvas_material(canvas, base))
        canvas_mat[canvas] = len(materials) - 1
        cutouts[canvas] = (c["cutout"], base)
    materials.append(gltf.untextured_material())
    untextured = len(materials) - 1

    special_mat = {}
    for mat, sp in geo.specials.items():
        if sp is None:
            continue
        image_index = None
        if sp["kind"] == "surface" or sp["texture"] is not None:  # everything but glass carries an image
            images.append(sp["image"])
            image_index = len(images) - 1
        materials.append(gltf.special_gltf_material(mat, sp, image_index))
        special_mat[mat] = len(materials) - 1

    drop_sword_trails(geo.nodes, geo.specials, report)

    # primitive keys -> material indices (glass and cutout materials are created on first use)
    cut_mat = {}
    for _, prims in geo.nodes:
        for pr in prims:
            kind, k = pr.pop("key")
            if kind == "glass":
                if "glass" not in special_mat:
                    materials.append(gltf.glass_material("glass_lens"))
                    special_mat["glass"] = len(materials) - 1
                pr["material"] = special_mat["glass"]
            elif kind == "cutout":
                if k not in cut_mat:
                    (colour, metal), base = cutouts[k]
                    rgba = colour.convert("RGBA")
                    rgba.putalpha(metal)
                    images.append(rgba)
                    materials.append(gltf.cutout_material(k, len(images) - 1, base))
                    cut_mat[k] = len(materials) - 1
                pr["material"] = cut_mat[k]
            elif kind == "canvas":
                pr["material"] = canvas_mat.get(k, untextured)
            elif kind == "special":
                pr["material"] = special_mat.get(k, untextured)
            else:
                pr["material"] = untextured

    save_material_data(out, geo.mats_seen, report)

    data = gltf.glb(geo.nodes, materials, images)
    with open(os.path.join(out, f"{slug}.glb"), "wb") as f:
        f.write(data)
    with open(os.path.join(out, "export_report.json"), "w", newline="\n") as f:
        json.dump(report, f, indent=1)
    print(f"   -> {os.path.join(out, slug + '.glb')} ({len(data) / 1e6:.1f} MB)")
    return out
