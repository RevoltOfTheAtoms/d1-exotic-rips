"""Rip the game images the viewer page uses into frontend/ (they are game assets, so they are not in the repo).

frontend/inspect_bg.png         the item-inspect screen backdrop (texture 80aa8380, lossless)
frontend/env_80a7451f.png       gear environment cube 1, all faces and mips, as an atlas (textures/env_atlas.py)
frontend/env_80a0856c.png       gear environment cube 2
"""

import os

from d1kit.config import FRONTEND_DIR
from d1kit.export.materials import ENV_CUBES
from d1kit.textures.decode import extract
from d1kit.textures.env_atlas import atlas

BACKDROP = 0x80AA8380  # inspect screen background (RGBA8, 1820x1024, fully opaque)


def rip_viewer_images():
    os.makedirs(FRONTEND_DIR, exist_ok=True)
    img, _ = extract(BACKDROP)
    img = img.convert("RGB")
    img.save(os.path.join(FRONTEND_DIR, "inspect_bg.png"))
    print(f"  frontend/inspect_bg.png  {img.size[0]}x{img.size[1]}")
    for cube in ENV_CUBES:
        img, _, mips = atlas(cube)
        img.save(os.path.join(FRONTEND_DIR, f"env_{cube:08x}.png"))
        print(f"  frontend/env_{cube:08x}.png  {img.size[0]}x{img.size[1]}, {mips} mips")
