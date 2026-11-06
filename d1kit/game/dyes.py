"""D1 gear dyes: item dye hashes -> dye tags (80801af4) and the bake used by Bungie's web gear shader (spasm).

Dye lookup: dye hash -> index in investment_globals_012c #99 -> asset hash at the same index in #41
            -> asset lookup -> stub -> dye tag 80801af4.
Dye tag layout (matches the web TGX dye's material_properties):
  0x10 slot_type_index, 0x30 decal alpha map transform, 0x50 specular properties,
  0x60 detail diffuse tag, 0x64 detail normal tag, 0x70 detail transform (scale xy, offset zw),
  0x80 detail normal contribution strength, 0x90 primary colour, 0xa0 secondary colour,
  0xb0 subsurface scattering strength, then the source path string.

Shading (spasm_webgl_gear_shader.js), all in linear space:
  detail   = (dye_diffuse.rgb * a + (1 - a) * 0.5) ^ 2.2         (sampled at uv * detail.xy + detail.zw)
  diffuse  = overlay(detail, diffuse)
  final    = mix(diffuse, overlay(diffuse, change_color), gearstack.r)
  overlay(back, front) = front * saturate(back * 4) + saturate(back - 0.25)
change_color_index (0..7): slot = index // 2, odd = secondary colour.
"""

import re
import struct

import numpy as np
from PIL import Image, ImageDraw

from d1kit.pkg.store import table
from d1kit.pkg.tags import asset_lookup, read
from d1kit.textures.decode import extract

_tables = None


def _dye_tables():
    global _tables
    if _tables is None:
        hashes = table(99)
        assets = table(41)
        (n,) = struct.unpack_from("<Q", hashes, 0x20)
        _tables = (list(struct.unpack_from(f"<{n}I", hashes, 0x30)), list(struct.unpack_from(f"<{n}I", assets, 0x30)))
    return _tables


def dye(dye_hash):
    hashes, assets = _dye_tables()
    if dye_hash not in hashes:
        return None
    stub = asset_lookup(assets[hashes.index(dye_hash)])
    if stub is None:
        return None
    tag = struct.unpack_from("<I", read(stub), 0x10)[0]
    d = read(tag)
    f = lambda o, n=4: list(struct.unpack_from(f"<{n}f", d, o))  # noqa: E731
    src = re.search(rb"content\\[ -~]+", d)
    return dict(
        hash=dye_hash,
        tag=f"{tag:08x}",
        slot=struct.unpack_from("<I", d, 0x10)[0],
        specular=f(0x50),
        detail_diffuse=struct.unpack_from("<I", d, 0x60)[0],
        detail_normal=struct.unpack_from("<I", d, 0x64)[0],
        detail_transform=f(0x70),
        detail_normal_strength=f(0x80),
        primary=f(0x90),
        secondary=f(0xA0),
        subsurface=f(0xB0),
        source=src.group().decode() if src else None,
    )


def item_dyes(item):
    """Dyes from the item definition (80801806): array of (u16 channel, u16 dye index), class 808018ea on 1.01,
    8080101c on 1.33."""
    from d1kit.game.items import _defs

    d = _defs().get(item["itemHash"])
    out = {}
    if d is None:
        return out
    hashes, _ = _dye_tables()
    for o in range(0, len(d) - 16, 8):
        if struct.unpack_from("<I", d, o + 8)[0] in (0x808018EA, 0x8080101C):  # 1.01, 1.33
            (n,) = struct.unpack_from("<Q", d, o)
            for i in range(n):
                _channel, idx = struct.unpack_from("<HH", d, o + 0x10 + i * 4)
                dy = dye(hashes[idx]) if idx < len(hashes) else None
                if dy:
                    out[dy["slot"]] = dy
            break
    return out


FORCE_DYE = 16  # cci + FORCE_DYE in the colour index map: dye the whole region, ignoring the gearstack R mask


def change_color_index(part):
    return (part["flags"] >> 4) & 0x7


def _overlay(back, front):
    return front * np.clip(back * 4.0, 0, 1) + np.clip(back - 0.25, 0, 1)


def color_index_map(size, uv_tris):
    """uv_tris: [(cci, (N,3,2) uv array)] -> (size,size) uint8 map of change colour index (255 = none)."""
    im = Image.new("L", (size, size), 255)
    dr = ImageDraw.Draw(im)
    for cci, tris in uv_tris:
        for t in tris * size:
            dr.polygon([tuple(p) for p in t], fill=int(cci))
    return np.asarray(im)


def bake(diffuse, gearstack, cci_map, dyes, detail_cache):
    """Apply dyes to a diffuse atlas (PIL RGB) -> PIL RGB. gearstack: PIL RGB(A). dyes: {slot: dye}."""
    size = diffuse.size[0]
    lin = (np.asarray(diffuse.convert("RGB")).astype(np.float32) / 255.0) ** 2.2
    mask = np.asarray(gearstack.convert("RGB")).astype(np.float32)[..., 0:1] / 255.0
    out = lin.copy()
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    u, v = (xx + 0.5) / size, (yy + 0.5) / size
    for cci in np.unique(cci_map):
        forced = FORCE_DYE <= cci < 255
        slot_cci = cci - FORCE_DYE if forced else cci
        if cci == 255 or slot_cci // 2 not in dyes:
            continue
        dy = dyes[slot_cci // 2]
        sel = cci_map == cci
        base = lin[sel]
        if dy["detail_diffuse"] not in detail_cache:
            try:
                img, _ = extract(dy["detail_diffuse"])
                detail_cache[dy["detail_diffuse"]] = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
            except Exception:
                detail_cache[dy["detail_diffuse"]] = None
        det = detail_cache[dy["detail_diffuse"]]
        col = np.array((dy["secondary"] if slot_cci & 1 else dy["primary"])[:3], np.float32)
        # Gear shader (80a3d145 & co., read from GCN): dyed = overlay(diffuse, overlay(detail, dye colour)),
        # blended over the plain diffuse twice by the gearstack R mask -> weight R^2
        if det is not None:
            sx, sy, ox, oy = dy["detail_transform"]
            h, w = det.shape[:2]
            px = (((u[sel] * sx + ox) % 1.0) * w).astype(int) % w
            py = (((v[sel] * sy + oy) % 1.0) * h).astype(int) % h
            dd = det[py, px][:, :3] ** 2.2
        else:
            dd = np.full((base.shape[0], 3), 0.5**2.2, np.float32)
        dyed = _overlay(base, _overlay(dd, col))
        m = 1.0 if forced else mask[sel] ** 2
        out[sel] = base * (1 - m) + dyed * m
    return Image.fromarray((np.clip(out, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8), "RGB")
