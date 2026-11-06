"""Material tags (class 80801ad7) and the shader families the exporter knows about."""

import struct

from d1kit.config import BUILD
from d1kit.pkg.tags import entry, read, tags_in

# Shared depth/shadow pass duplicates of every draw: never exported.
PASS_MATERIALS = {0x80AAE10B, 0x80AAE10C}

# Textures that mark a material as plated gear surface (drawn from the canvas atlas): shared gear detail noise and
# the gear environment cube.
GEAR_TEXTURES = {0x80A0846A, 0x80A7451F}
if BUILD != "1.01":
    # 1.33 re-authored many gear materials onto a new shader whose only shared texture is this 64x64 env cube.
    # (1.01 also uses it on a few lens/glow materials, so it is not added there: keeps 1.01 exports unchanged.)
    GEAR_TEXTURES = GEAR_TEXTURES | {0x80A0856C}

# Gear pixel shaders, read from their GCN code (d1kit/gpu/gcn_dis.py). Each writes surface colour =
#   diffuse_dyed + spec_tint * reflection, with reflection from the material's environment cube:
#   A 80a3d145, 80a3c693 (most guns): refl = env * mask * min(1, B*c7.x + c8.x) * (G + c5.x)
#                                      spec_tint = diffuse*c9.x + c9.y        (mask = 2D tex tiled by c6.xy)
#   B 80a38a95 (Gjallarhorn, ...):     refl = env * (c6.x + c5.x*B) * lerp(c7, c8, B).rgb*.a * (1 - R)
#                                      spec_tint = diffuse*c9.x + c9.y
#   C 80a39b99 (swords):               refl = env * G*c6.x * B * (mask + c8.x), spec_tint = 1
# R/G/B = gearstack channels. The cube lookup is view dependent; baked here as the cube's mean colour.
SHINE_FAMILY = {"80a3d145": "A", "80a3c693": "A", "80a38a95": "B", "80a39b99": "C"}

LENS_PS = "80a3d10c"  # scope lens shader (env cube reflection over a dark tint)

# Additive glow shaders used by effect passes (flag 0x20) for lights on the gun (Invective's orange dots, Thorn's
# green glow). Exported exactly as the shader computes them from the material data, nothing made up:
#   80aad077: out = texture.rgb * texture.a * c[2].rgb * c[3].x          (x the frame's exposure)
#   80aadb76: out = c[3].rgb * c[2].rgb * c[2].w * c[4].x
# The image holds the per-texel colour, the scalar (c[3].x / c[4].x) is the glTF emissive strength, and the viewer
# adds it on top (additive, like the game's pass). Where the data holds 0 the game sets the strength at runtime: those
# are shown at strength 1 and flagged (material extras d1RuntimeStrength), the colour still comes from the data.
GLOW_PS = {"80aad077", "80aadb76"}

# Environment cubes the viewer samples per pixel (frontend/env_<tag>.png atlases, d1kit/textures/env_atlas.py); the id
# is stored in the env texture's alpha (id * 64). Other cubes stay baked into the base colour as their average.
ENV_CUBES = {0x80A7451F: 1, 0x80A0856C: 2}
ENV_TINT_SCALE = 4.0  # env texture rgb = sqrt(tint / scale)

_cache = {}


def material_info(tag):
    """80801ad7: shader stage tags, texture slots, sampler tags, float4 constants. Returns a fresh dict."""
    d = read(tag)
    info = dict(tag=f"{tag:08x}", textures=[], samplers=[], constants=[], shaders={})
    for o, c in tags_in(d):
        p, e = entry(c)
        kind = f"t{e['type']}/s{e['subtype']}"
        if e["type"] == 32 and e["subtype"] in (8, 9):
            info["shaders"]["ps" if e["subtype"] == 8 else "vs"] = f"{c:08x}"
        elif e["type"] == 32:
            (slot,) = struct.unpack_from("<I", d, o - 4)
            info["textures"].append(dict(slot=slot, tag=f"{c:08x}", kind=kind))
        elif e["type"] == 16:
            info["samplers"].append(f"{c:08x}")
    # float4 constant arrays (class 80800090): vertex-shader constants first when present, pixel-shader last
    arrays = []
    for o in range(0, len(d) - 16, 8):
        if struct.unpack_from("<I", d, o + 8)[0] == 0x80800090:
            (n,) = struct.unpack_from("<Q", d, o)
            arrays.append([list(struct.unpack_from("<4f", d, o + 0x10 + i * 16)) for i in range(n)])
    if arrays:
        info["constants"] = arrays[-1]
        if len(arrays) > 1:
            info["vs_constants"] = arrays[0]
    return info


def cached_info(tag):
    """material_info, cached: for read-only lookups (don't modify the result)."""
    if tag not in _cache:
        _cache[tag] = material_info(tag)
    return _cache[tag]
