"""glTF output: material definitions and a minimal GLB writer.

Material extras read by the viewer (frontend/d1light.js):
    d1Env, d1EnvTintScale   occlusionTexture is the game's per-pixel env reflection tint, not occlusion
    d1Additive              game glow pass: drawn additively
    d1RuntimeStrength       the glow's strength is set by the game at runtime (shown at 1)
    d1CalibratedStrength    strength calibrated against an in-game screenshot
    d1ViewLut               glow brightness by view angle (33 samples of N.V from -1 to 1)
    d1RuntimeColour         the surface colour depends on runtime values (shown as stored)
    d1Approx                an approximation (see export/overrides.py); the note is shown on the weapon page
"""

import io
import json
import struct

import numpy as np

from d1kit.export.materials import ENV_TINT_SCALE

GLASS_COLOUR = [0.02, 0.03, 0.04, 0.45]


def canvas_material(canvas, base):
    """Plated surface: images base..base+3 = base colour, normal, ORM, env reflection."""
    return dict(
        name=f"canvas{canvas}",
        pbrMetallicRoughness=dict(
            baseColorTexture=dict(index=base),
            metallicRoughnessTexture=dict(index=base + 2),
            metallicFactor=1.0,
            roughnessFactor=1.0,
        ),
        normalTexture=dict(index=base + 1),
        # not occlusion: the viewer reads this as the game's env reflection (d1light.js)
        occlusionTexture=dict(index=base + 3),
        extras=dict(d1Env=True, d1EnvTintScale=ENV_TINT_SCALE),
        doubleSided=False,
    )


def cutout_material(canvas, colour_index, base):
    """Decal on the plates, alpha-tested against gearstack B (Bungie's D1 shader discards where B is 0)."""
    return dict(
        name=f"canvas{canvas}_cutout",
        alphaMode="MASK",
        alphaCutoff=0.5,
        doubleSided=True,
        pbrMetallicRoughness=dict(
            baseColorTexture=dict(index=colour_index),
            metallicRoughnessTexture=dict(index=base + 2),
            metallicFactor=1.0,
            roughnessFactor=1.0,
        ),
        normalTexture=dict(index=base + 1),
        occlusionTexture=dict(index=base + 3),
        extras=dict(d1Env=True, d1EnvTintScale=ENV_TINT_SCALE),
    )


def untextured_material():
    return dict(
        name="untextured",
        pbrMetallicRoughness=dict(baseColorFactor=[0.35, 0.35, 0.37, 1], metallicFactor=0.6, roughnessFactor=0.5),
    )


def glass_material(name):
    """Lens / runtime render target: dark glass."""
    return dict(
        name=name,
        alphaMode="BLEND",
        doubleSided=True,
        pbrMetallicRoughness=dict(baseColorFactor=GLASS_COLOUR, metallicFactor=0.0, roughnessFactor=0.05),
    )


def special_gltf_material(mat, sp, image_index):
    """glTF material for a special (export/specials.py); image_index = its image, or None for glass."""
    approx = {"d1Approx": sp["approx"]} if sp.get("approx") else {}
    if sp["kind"] == "surface":  # opaque G-buffer surface: the colour its game shader writes from the data
        return dict(
            name=f"surface_{mat:08x}",
            doubleSided=True,
            pbrMetallicRoughness=dict(
                baseColorTexture=dict(index=image_index), metallicFactor=0.0, roughnessFactor=0.6
            ),
            extras=dict(d1RuntimeColour=sp["runtime"]),
        )
    if sp["texture"] is None:
        return glass_material(f"glass_{mat:08x}")
    if sp["kind"] == "decal":  # painted marking: its own colour and alpha, lit like the surface
        return dict(
            name=f"decal_{mat:08x}",
            alphaMode="BLEND",
            doubleSided=True,
            pbrMetallicRoughness=dict(
                baseColorTexture=dict(index=image_index), metallicFactor=0.0, roughnessFactor=0.7
            ),
            **({"extras": approx} if approx else {}),
        )
    if sp.get("texture") == "effect":  # game glow pass: additive light, colour and strength from the data
        return dict(
            name=f"glow_{mat:08x}",
            alphaMode="BLEND",
            doubleSided=True,
            pbrMetallicRoughness=dict(baseColorFactor=[0, 0, 0, 1], metallicFactor=0.0, roughnessFactor=1.0),
            emissiveTexture=dict(index=image_index),
            emissiveFactor=[1.0, 1.0, 1.0],
            extensions={"KHR_materials_emissive_strength": {"emissiveStrength": sp["strength"]}},
            extras=dict(
                d1Additive=True,
                d1RuntimeStrength=sp["runtime"],
                **({"d1ViewLut": sp["view_lut"]} if sp.get("view_lut") else {}),
                **({"d1CalibratedStrength": True} if sp.get("calibrated") else {}),
                **approx,
            ),
        )
    # fallback glow overlay: emissive, alpha from brightness
    return dict(
        name=f"overlay_{mat:08x}",
        alphaMode="BLEND",
        doubleSided=True,
        pbrMetallicRoughness=dict(
            baseColorTexture=dict(index=image_index),
            baseColorFactor=[0, 0, 0, 1],
            metallicFactor=0.0,
            roughnessFactor=1.0,
        ),
        emissiveTexture=dict(index=image_index),
        emissiveFactor=[1.0, 1.0, 1.0],
    )


def glb(nodes_meshes, materials, images):
    """Minimal GLB writer. nodes_meshes: [(name, [prim dict])]; prim: pos, nrm, uv, idx, material."""
    bin_ = bytearray()
    views, accessors = [], []

    def add_view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(
            dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), **({"target": target} if target else {}))
        )
        bin_.extend(data)
        return len(views) - 1

    def add_acc(arr, typ, ctype, target):
        v = add_view(arr.tobytes(), target)
        acc = dict(bufferView=v, componentType=ctype, count=int(arr.shape[0]), type=typ)
        if typ == "VEC3" and ctype == 5126:
            acc["min"] = arr.min(axis=0).tolist()
            acc["max"] = arr.max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    gl_meshes, gl_nodes = [], []
    for name, prims in nodes_meshes:
        gp = []
        for p in prims:
            attrs = {"POSITION": add_acc(p["pos"].astype(np.float32), "VEC3", 5126, 34962)}
            if p.get("nrm") is not None:
                attrs["NORMAL"] = add_acc(p["nrm"].astype(np.float32), "VEC3", 5126, 34962)
            if p.get("uv") is not None:
                attrs["TEXCOORD_0"] = add_acc(p["uv"].astype(np.float32), "VEC2", 5126, 34962)
            ind = add_acc(p["idx"].astype(np.uint32).reshape(-1), "SCALAR", 5125, 34963)
            gp.append(dict(attributes=attrs, indices=ind, material=p["material"]))
        gl_meshes.append(dict(name=name, primitives=gp))
        gl_nodes.append(dict(name=name, mesh=len(gl_meshes) - 1))
    gl_images = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        gl_images.append(dict(bufferView=add_view(buf.getvalue()), mimeType="image/png"))
    while len(bin_) % 4:
        bin_.append(0)
    used_ext = sorted({k for m in materials for k in m.get("extensions", {})})
    gltf = dict(
        asset=dict(version="2.0", generator="d1-ps4-weapon-export"),
        **({"extensionsUsed": used_ext} if used_ext else {}),
        scene=0,
        scenes=[dict(nodes=list(range(len(gl_nodes))))],
        nodes=gl_nodes,
        meshes=gl_meshes,
        materials=materials,
        images=gl_images,
        textures=[dict(source=i, sampler=0) for i in range(len(gl_images))],
        samplers=[dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071)],
        accessors=accessors,
        bufferViews=views,
        buffers=[dict(byteLength=len(bin_))],
    )
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_)
    return out
