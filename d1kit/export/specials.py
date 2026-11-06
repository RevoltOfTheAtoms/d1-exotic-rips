"""Materials that aren't plated gear surface: decals, glows, lenses and shader-baked surfaces.

Each classifier returns a "special" dict the glTF writer turns into a material:
    kind "decal"    texture with its own alpha, drawn as a painted marking
    kind "glow"     texture="effect": additive light (game glow pass), with strength and runtime flags
                    otherwise: opaque texture shown emissive, alpha from brightness (fallback overlay)
    kind "surface"  an opaque surface whose colour is the game shader's own output (run on the CPU)
    kind "glass"    texture None: lens / runtime render target, drawn as dark glass
or None for plated gear materials (drawn from the canvas atlas).
"""

import numpy as np
from PIL import Image

from d1kit.export.materials import GEAR_TEXTURES, GLOW_PS, SHINE_FAMILY, material_info
from d1kit.export.overrides import APPROX_ORB, SWORD_GLOW_STRENGTH, approx_orb
from d1kit.pkg.tags import entry, read
from d1kit.textures.decode import extract
from d1kit.textures.texinfo import texinfo

GRID = 256  # texels per side when running a shader over a material's UV space


def _uv_grid(n_side):
    yy, xx = np.mgrid[0:n_side, 0:n_side].astype(np.float32)
    return ((xx + 0.5) / n_side).ravel(), ((yy + 0.5) / n_side).ravel()


def _samplers(mi):
    """The material's textures as emulator samplers, in shader slot order (16-byte t32/s7 stubs aren't bound)."""
    from d1kit.gpu import shader_bake

    tex, k = {}, 0
    for t in sorted(mi["textures"], key=lambda t: t["slot"]):
        if t.get("kind") == "t32/s7":
            continue
        tag = int(t["tag"], 16)
        ti = texinfo(tag)
        tex[k] = (
            shader_bake.const_sampler(shader_bake.cube_mean(tag))
            if ti["type_name"] == "cube"
            else shader_bake.sampler(shader_bake.tex_array(tag))
        )
        k += 1
    return tex


def special_material(mat):
    """Classify a material (see the module docstring)."""
    if mat in APPROX_ORB:
        return approx_orb(mat)
    mi = material_info(mat)
    tex = [int(t["tag"], 16) for t in mi["textures"]]
    if GEAR_TEXTURES & set(tex):
        return None
    # a plated gear shader is gear surface whatever extra textures it carries (e.g. Khvostov's stock material
    # 80a839a3: ps 80a3d145 with its own env cube 80a7dcf3 and a 2D texture)
    if mi["shaders"].get("ps") in SHINE_FAMILY:
        return None
    for t in tex:
        try:
            if texinfo(t)["type_name"] != "2d":
                continue
            img, _ = extract(t)
        except Exception:
            continue
        rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
        if rgba[..., 3].min() < 250:  # real transparency: keep it (dark decals must stay visible)
            return dict(texture=t, image=Image.fromarray(rgba.astype(np.uint8), "RGBA"), kind="decal")
        surf = gbuffer_surface(mi)
        if surf is not None:  # an opaque, lit surface in the game: its shader's own colour from the data
            return surf
        rgba[..., 3] = np.clip(rgba[..., :3].max(axis=2) * 1.5, 0, 255)
        return dict(texture=t, image=Image.fromarray(rgba.astype(np.uint8), "RGBA"), kind="glow")
    return dict(texture=None, image=None, kind="glass")


def gbuffer_surface(mi):
    """Special material whose pixel shader writes the G-buffer (mrt0 + mrt1: an opaque surface the lights shade).
    Runs the shader (gcn_emu) over a UV grid with the material's stored constants and textures and returns
    {kind 'surface', image, colour}, or None if it doesn't write the G-buffer or can't be run. Values the game fills
    at runtime are 0 in the data and stay 0 (flagged 'runtime' when the colour depends on them)."""
    ps = mi["shaders"].get("ps")
    if not ps:
        return None
    try:
        from d1kit.gpu import shader_bake
        from d1kit.gpu.gcn_dis import disasm_bytes

        _, e = entry(int(ps, 16))
        if not any("exp mrt1" in line for line in disasm_bytes(read(e["reference"]))):
            return None
        n_side = GRID
        n = n_side * n_side
        u, v = _uv_grid(n_side)
        one, zero = np.ones(n, np.float32), np.zeros(n, np.float32)
        tex = _samplers(mi)
        attrs = {
            0: np.stack([zero, zero, one, one], -1),
            1: np.stack([u, v, u, v], -1),
            2: np.stack([zero, zero, one, zero], -1),
            3: np.stack([u, v, u, v], -1),
            4: np.stack([zero, zero, zero, one], -1),
        }

        def run(fill):
            # fill: value put into all-zero float4 slots (the runtime placeholders); 0 = the data as stored
            cs = [list(c) if any(c) else [fill] * 4 for c in mi["constants"]]
            cb = [f for c in cs for f in c] + [0.0] * 64
            o = shader_bake.shader(int(ps, 16)).run(n, cb, [0.0] * 64, tex, attrs, quad_w=n_side).get("mrt0")
            return None if o is None else o[:, :3]

        out = run(0.0)
        # undefined with the stored data (NaN: e.g. Ice Breaker's 80a39825, whose band pattern divides by
        # runtime-set slots): the data can't give its colour, keep the material's previous handling
        if out is None or np.isnan(out).mean() > 0.01:
            return None
        out = np.nan_to_num(out)
        probe = run(1.0)
        runtime = probe is not None and not np.allclose(probe, out, atol=1e-4)  # colour depends on runtime slots
        img = Image.fromarray(
            (np.clip(out, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8).reshape(n_side, n_side, 3), "RGB"
        )
        return dict(
            texture=None,
            image=img,
            kind="surface",
            runtime=bool(runtime),
            colour=[float(x) for x in np.clip(out.mean(0), 0, 1)],
        )
    except Exception:
        return None


def glow_effect(mat):
    """Effect-pass material that is a plain light on the gun (GLOW_PS): {kind 'glow', image, strength} or None."""
    mi = material_info(mat)
    ps = mi["shaders"].get("ps")
    c = mi["constants"]
    if ps not in GLOW_PS or len(c) < (4 if ps == "80aad077" else 5):
        return None
    if ps == "80aad077":
        tex = [int(t["tag"], 16) for t in mi["textures"] if t.get("kind") != "t32/s7"]
        if not tex:
            return None
        from d1kit.gpu import shader_bake

        a = shader_bake.tex_array(tex[0])  # linear, as the GPU samples it (sRGB textures decoded)
        rgb = a[..., :3] * a[..., 3:4] * np.array(c[2][:3], np.float32)
        strength = float(c[3][0])
    else:
        rgb = np.ones((4, 4, 3), np.float32) * np.array(c[3][:3], np.float32) * np.array(c[2][:3], np.float32) * c[2][3]
        strength = float(c[4][0])
    # the shader's output is linear; glTF emissive textures are sRGB-encoded
    rgb = np.clip(rgb, 0, 1) ** (1 / 2.2)
    runtime = strength == 0.0  # stored 0: the game sets the strength at runtime; shown at 1, flagged
    return dict(
        texture="effect",
        kind="glow",
        strength=1.0 if runtime else strength,
        runtime=runtime,
        image=Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB"),
    )


def sword_effect(mat):
    """Sword blade energy (effect pass, additive, its own animated shader per sword): the game shader run over the
    part's UV space (gcn_emu) with the material's stored constants. Its strength and fill-level slots are 0 in the data
    (set at runtime from the sword's energy); they are set to 1 = full strength / full blade (flagged runtime), the
    frame exposure to 1 and the view along the normal (the effect has a rim term, sampled into a view curve).
    Returns a 'glow' special like glow_effect, or None when the pass writes no colour (e.g. alpha-only bloom masks).
    Only used when overrides.SWORD_FX is on."""
    from d1kit.gpu import shader_bake

    mi = material_info(mat)
    ps = mi["shaders"].get("ps")
    if not ps or not mi["constants"] or not [t for t in mi["textures"] if t.get("kind") != "t32/s7"]:
        return None  # texture-less passes are light cards / haze planes, not the blade surface
    try:
        n_side = GRID
        u, v = _uv_grid(n_side)
        tex = _samplers(mi)
        cs = [list(c) if any(c) else [1.0] * 4 for c in mi["constants"]]  # runtime slots -> 1 (full)
        cb = [f for c in cs for f in c] + [0.0] * 64
        frame = [0.0] * 64
        frame[6] = frame[7] = 1.0  # 0x18: frame exposure pair
        frame[28:31] = [0.0, 0.0, 1.0]  # 0x70: camera position (view along +z)
        sh = shader_bake.shader(int(ps, 16))

        def run(nv, uu, vv):
            m = len(uu)
            o1, z1 = np.ones(m, np.float32), np.zeros(m, np.float32)
            nx = np.sqrt(max(0.0, 1 - nv * nv))
            at = {
                0: np.stack([o1 * nx, z1, o1 * nv, o1], -1),
                1: np.stack([uu, vv, uu, vv], -1),
                2: np.stack([z1, z1, z1, o1], -1),
                3: np.stack([uu, vv, uu, vv], -1),
                4: np.stack([z1, z1, z1, o1], -1),
            }
            o = sh.run(m, cb, frame, tex, at).get("mrt0")
            return None if o is None else np.clip(np.nan_to_num(o[:, :3]), 0, None)

        out = run(1.0, u, v)  # colour per texel, facing the camera
        if out is None:
            return None
        peak = float(out.max())
        if peak < 1e-4:
            return None
        # view-angle curve f(N.V) from the shader on a probe grid: glow = colour(uv) * f (checked separable)
        pu, pv = u[::97], v[::97]
        base = run(1.0, pu, pv).sum(1)
        msk = base > 1e-6
        lut = []
        for nv in np.linspace(-1, 1, 33):
            o = run(float(nv), pu, pv).sum(1)
            lut.append(round(float((o[msk] / base[msk]).mean()) if msk.any() else 0.0, 4))
        img = Image.fromarray(
            ((out / peak) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8).reshape(n_side, n_side, 3), "RGB"
        )
        # The game scales this glow by its per-frame auto-exposure (frame cb 0x18) and the sword's live energy, neither
        # in the files: the strength is calibrated (overrides.SWORD_GLOW_STRENGTH), flagged d1CalibratedStrength.
        return dict(
            texture="effect",
            kind="glow",
            strength=SWORD_GLOW_STRENGTH,
            runtime=True,
            calibrated=True,
            image=img,
            sword=True,
            view_lut=lut,
        )
    except Exception:
        return None
