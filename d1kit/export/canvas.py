"""Canvas atlases: the weapon's plate textures composited per canvas, dyed, and baked with the game's own shaders.

A weapon's plated parts share up to a few "canvases". Each canvas has three layers built from the part plates:
    diffuse (RGB, sRGB), normal (RGB, DirectX), gearstack (RGBA: R dye mask, G smoothness, B metal)
The dyed diffuse is then run through each part material's pixel shader (gcn_emu) to get the colour the game writes,
plus the per-pixel environment reflection and BRDF parameters the viewer's game lighting uses.
"""

import os

import numpy as np
from PIL import Image

from d1kit.export.materials import ENV_CUBES, ENV_TINT_SCALE, SHINE_FAMILY, material_info
from d1kit.game.dyes import FORCE_DYE, bake, color_index_map
from d1kit.textures.decode import all_texels, extract
from d1kit.textures.texinfo import texinfo


def pow2(n):
    p = 256
    while p < n:
        p *= 2
    return p


def canvas_size(plates):
    """Atlas size of a canvas: next power of two (min 256) covering its plates. plates: [(part idx, channel, plate)]."""
    return pow2(max(max(pl["x"] + pl["w"], pl["y"] + pl["h"]) for _, _, pl in plates))


def on_plates(tri_uvs, rects, share=0.9):
    """True when most triangle centroids (N,3,2 uvs) fall inside the part's plate rectangles."""
    if not rects or not len(tri_uvs):
        return False
    c = tri_uvs.mean(axis=1)
    inside = np.zeros(len(c), bool)
    for x0, y0, x1, y1 in rects:
        inside |= (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
    return inside.mean() >= share


def material_index_map(size, mat_tris):
    """Rasterise each part's material into the atlas: (size,size) uint8 index map (255 = none) + material list."""
    mats = sorted({m for m, _ in mat_tris})[:254]
    idx = {m: i for i, m in enumerate(mats)}
    return color_index_map(size, [(idx[m], t) for m, t in mat_tris if m in idx]), mats


def composite_layers(plates, parts, size, part_dir):
    """Paste every plate texture into the canvas layers {0: diffuse, 1: normal, 2: gearstack}. The raw plate
    textures are also written to part_dir (DDS + PNG)."""
    layers = {
        0: Image.new("RGB", (size, size), (128, 128, 128)),
        1: Image.new("RGB", (size, size), (128, 128, 255)),
        2: Image.new("RGBA", (size, size), (0, 128, 255, 255)),
    }
    for pi, ch, pl in plates:
        img, info = extract(
            pl["texture"],
            os.path.join(part_dir, f"slot{parts[pi]['slot']}_{pl['texture']:08x}_ch{ch}"),
            layout="linear",
        )
        if img.size != (pl["w"], pl["h"]):
            img = img.resize((pl["w"], pl["h"]), Image.LANCZOS)
        layers[ch].paste(img.convert(layers[ch].mode), (pl["x"], pl["y"]))
    return layers


# --- fallback: hand-written gear reflection (used where a shader can't be emulated) ---------------------------------


def _tex_mean(tag):
    t = all_texels(tag) if texinfo(tag)["type_name"] == "cube" else None
    if t is None:
        img, _ = extract(tag)
        t = np.asarray(img.convert("RGB")).astype(np.float32).reshape(-1, 3) / 255.0
    return (t**2.2).mean(0)  # sRGB textures (GCN num format 9) -> linear


def _shine_params(mat, cache):
    if mat in cache:
        return cache[mat]
    mi = material_info(mat)
    fam = SHINE_FAMILY.get(mi["shaders"].get("ps"))
    prm = None
    if fam:
        env = mask = None
        for t in mi["textures"]:
            ti = texinfo(int(t["tag"], 16))
            try:
                m = _tex_mean(int(t["tag"], 16))
            except Exception:
                continue
            if ti["type_name"] == "cube":
                env = m
            else:
                mask = float(m.mean())
        c = [np.array(x, np.float32) for x in mi["constants"]]
        if env is not None and len(c) > 9:
            prm = dict(fam=fam, env=env, mask=1.0 if mask is None else mask, c=c)
    cache[mat] = prm
    return prm


def gear_shine(lin, gs, mat_map, mats, cache):
    """The gear shader families' reflection (materials.SHINE_FAMILY), with the cube's mean colour."""
    out = lin.copy()
    R, G, B = gs[..., 0], gs[..., 1], gs[..., 2]
    for i, mat in enumerate(mats):
        prm = _shine_params(mat, cache)
        if prm is None:
            continue
        sel = mat_map == i
        if not sel.any():
            continue
        c, env, alb = prm["c"], prm["env"], lin[sel]
        r, g, b = R[sel][:, None], G[sel][:, None], B[sel][:, None]
        if prm["fam"] == "A":
            refl = env * prm["mask"] * np.clip(b * c[7][0] + c[8][0], 0, 1) * (g + c[5][0])
            out[sel] = alb + (alb * c[9][0] + c[9][1]) * refl
        elif prm["fam"] == "B":
            tint = c[7] + (c[8] - c[7]) * b
            refl = env * (c[6][0] + c[5][0] * b) * tint[:, :3] * tint[:, 3:4] * (1 - r)
            out[sel] = alb + (alb * c[9][0] + c[9][1]) * refl
        else:
            out[sel] = alb + env * g * c[6][0] * b * (prm["mask"] + c[8][0])
    return out


# --- the game's shaders ----------------------------------------------------------------------------------------------


def shader_bake_canvas(lin, layers, gs, cci_map, mat_map, mat_list, dyes, cache, log):
    """Surface colour from the game's own pixel shaders (gcn_emu), per (material, change colour index) group.
    Groups whose shader can't run keep the dye bake + gear_shine.
    Returns (colour, mask of emulated px, brdf (row parameter, gloss), (env tint, env mip level, env cube id))."""
    from d1kit.gpu import shader_bake

    size = lin.shape[0]
    dif = np.asarray(layers[0].convert("RGBA")).astype(np.float32) / 255.0
    dif[..., :3] = dif[..., :3] ** 2.2  # plate diffuse is sRGB (num format 9)
    nrm = np.asarray(layers[1].convert("RGBA")).astype(np.float32) / 255.0
    gsa = np.asarray(layers[2].convert("RGBA")).astype(np.float32) / 255.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    uv = np.stack([(xx + 0.5) / size, (yy + 0.5) / size], -1)
    out, done = lin.copy(), np.zeros(lin.shape[:2], bool)
    brdf = np.zeros(lin.shape[:2] + (2,), np.float32)  # (row parameter, gloss) for the viewer's game lighting
    # environment reflection left for the viewer: tint (x cube sample), the shader's mip level, cube id (ENV_CUBES)
    env_tint = np.zeros(lin.shape[:2] + (3,), np.float32)
    env_lod = np.zeros(lin.shape[:2], np.float32)
    env_id = np.zeros(lin.shape[:2], np.uint8)
    fallback = gear_shine(lin, gs, mat_map, mat_list, cache)
    for i, mat in enumerate(mat_list):
        msel = mat_map == i
        if not msel.any():
            continue
        mi = cache.setdefault(("mi", mat), material_info(mat))
        for cci in np.unique(cci_map[msel]):
            sel = msel & (cci_map == cci)
            forced = FORCE_DYE <= cci < 255
            c = cci - FORCE_DYE if forced else (0 if cci == 255 else cci)
            try:
                res = shader_bake.bake_group(
                    mi, dyes.get(c // 2), bool(c & 1), dif[sel], nrm[sel], gsa[sel], uv[sel], force_dye=forced
                )
            except Exception as ex:  # unsupported instruction etc.: keep the hand bake for these pixels
                res = None
                log[f"{mat:08x}"] = f"fallback: {ex}"[:200]
            if res is None:
                out[sel] = fallback[sel]
                continue
            res, br, env = res
            out[sel] = res
            if env is not None and env["cube"] in ENV_CUBES:
                out[sel] = env["base"]
                env_tint[sel] = env["tint"]
                env_lod[sel] = env["lod"]
                env_id[sel] = ENV_CUBES[env["cube"]]
            if br is not None:
                brdf[sel] = br
            done |= sel
            log.setdefault(f"{mat:08x}", f"emulated {mi['shaders'].get('ps')}")
    return out, done, brdf, (env_tint, env_lod, env_id)


def bake_canvas(canvas, plates, parts, uv_tris, mat_tris, item_dye, caches, out_dir, preview_size, log):
    """Build one canvas: composite, dye, shader-bake. Writes the atlas PNGs to out_dir/textures/atlas.
    Returns dict(size, images=[base colour, normal, ORM, env], cutout=(colour, metal mask))."""
    size = canvas_size(plates)
    layers = composite_layers(plates, parts, size, os.path.join(out_dir, "textures", "parts"))
    atlas_dir = os.path.join(out_dir, "textures", "atlas")
    layers[0].save(os.path.join(atlas_dir, f"canvas{canvas}_diffuse.png"))
    layers[1].save(os.path.join(atlas_dir, f"canvas{canvas}_normal.png"))
    layers[2].save(os.path.join(atlas_dir, f"canvas{canvas}_gearstack.png"))
    cci_map = color_index_map(size, uv_tris)
    regions = np.where(cci_map == 255, 0, (cci_map.astype(np.int32) % FORCE_DYE + 1) * 30).astype(np.uint8)
    Image.fromarray(regions).save(os.path.join(atlas_dir, f"canvas{canvas}_dyeregions.png"))
    dyed = bake(layers[0], layers[2], cci_map, item_dye, caches["detail"])
    dyed.save(os.path.join(atlas_dir, f"canvas{canvas}_diffuse_dyed.png"))
    # gearstack: R dye mask, G smoothness, B metal (bare metal vs paint: inlays like Ace of Spades' spade)
    gs = np.asarray(layers[2]).astype(np.float32) / 255.0
    # The game's gear shaders add their environment-cube reflection into the surface colour they write. Bake that in,
    # per pixel by each part's material; the viewer then doesn't reflect a second time.
    mat_map, mat_list = material_index_map(size, mat_tris)
    lin = (np.asarray(dyed).astype(np.float32) / 255.0) ** 2.2
    lin, shined, brdf, (env_tint, env_lod, env_id) = shader_bake_canvas(
        lin, layers, gs, cci_map, mat_map, mat_list, item_dye, caches["shine"], log
    )
    dyed = Image.fromarray((np.clip(lin, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8), "RGB")
    # ORM texture, read by the viewer's game-lighting shader: R = BRDF row parameter (1 = not baked by the game
    # shader -> standard PBR), G = roughness (1 - the game's gloss where baked), B = metal, or where baked the env
    # mip level / 8 (the game's reflection is already in the base colour)
    orm = np.stack(
        [
            np.where(shined, brdf[..., 0], 1.0),
            np.where(shined, 1.0 - brdf[..., 1], 1.0 - gs[..., 1] * 0.85),
            np.where(shined, np.clip(env_lod / 8.0, 0, 1), gs[..., 2]),
        ],
        -1,
    )
    env_img = np.concatenate([np.sqrt(np.clip(env_tint / ENV_TINT_SCALE, 0, 1)), (env_id[..., None] * 64 / 255.0)], -1)
    nm = np.asarray(layers[1]).copy()
    nm[..., 1] = 255 - nm[..., 1]  # DirectX -> OpenGL normal map
    ps_ = (preview_size, preview_size) if preview_size and size > preview_size else (size, size)
    images = [
        dyed.resize(ps_, Image.LANCZOS),
        Image.fromarray(nm).resize(ps_, Image.LANCZOS),
        Image.fromarray((orm * 255).astype(np.uint8)).resize(ps_, Image.LANCZOS),
        Image.fromarray((env_img * 255 + 0.5).astype(np.uint8), "RGBA").resize(ps_, Image.NEAREST),
    ]
    metal = Image.fromarray((gs[..., 2] * 255).astype(np.uint8)).resize(ps_, Image.LANCZOS)
    return dict(size=size, images=images, cutout=(images[0], metal))
