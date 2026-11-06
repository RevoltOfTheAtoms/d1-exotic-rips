"""Per-weapon decisions that aren't read from the game data: every one is listed here, with its reason.

The export is otherwise "organic" (everything comes from the dump). These are the exceptions, each a deliberate
choice made by comparing against in-game PS4 screenshots, and each flagged in the exported files.
"""

import numpy as np
from PIL import Image

# --- materials left out ---------------------------------------------------------------------------------------------
# Not a data problem: the meshes are in the game files, but the game hides or dissolves them at runtime.
# A skipped material still claims its triangle range, so other passes on the same triangles don't take its place.
SKIP_MATERIALS = {
    0x80A7D49D: "Touch of Malice sight: the strands through the orb",
    0x80A7D49F: "Touch of Malice sight: same strands (second pass on the same triangles)",
    # inner orb: black in the data (c1/c5/c8 = 0) and cut away by its alpha test at runtime; the PS4 reference
    # shows an empty ring, so it is left out rather than drawn as a black ball
    0x80A7D49C: "Touch of Malice sight: inner orb (dissolved in game; empty ring in the reference)",
}

# --- approximations (flagged d1Approx in the material extras; the viewer shows the note) -----------------------------
# Touch of Malice's sight orb: its colours, texture tiling, glow strength and 3 of its glow textures are set at
# runtime (0 / unbound in the files), so it can't be ripped as the game draws it. Built only from its own game data:
#   outer shell 80a7d498 (ps 80a7d4a0): black (c0), alpha-tested: kept where stars (809f8016) * 2 (c5.x) * radial
#     mask (80a6ad9a) >= the runtime threshold c7.x; shown with threshold 0.5. Tiling: the mesh's own UVs.
APPROX_ORB = {0x80A7D498: "shell"}
ORB_NOTE = (
    "Sight orb shown as the black specks of its star texture; the game sets how much of it is cut away "
    "while running (cut-off chosen here)"
)
ORB_CUTOFF = 0.5

# --- sword blade energy ---------------------------------------------------------------------------------------------
# The blade glow passes are gated by runtime slots (strength, fill level) and the frame's auto-exposure. Exporting
# them with those set to "full" lit the whole blade, which looked wrong against the in-game reference, so they are
# off. sword_effect() in specials.py keeps the work in case the runtime values are found.
SWORD_FX = False
SWORD_GLOW_STRENGTH = 0.03  # calibrated by eye to an in-game screenshot (flagged d1CalibratedStrength)


def approx_orb(mat):
    """Touch of Malice sight orb shell as black star specks (see APPROX_ORB)."""
    from d1kit.gpu import shader_bake

    stars = shader_bake.tex_array(0x809F8016)[..., 0]
    mask = (
        np.asarray(
            Image.fromarray((shader_bake.tex_array(0x80A6AD9A)[..., 0] * 255).astype(np.uint8)).resize(
                stars.shape[::-1], Image.BILINEAR
            )
        ).astype(np.float32)
        / 255
    )
    keep = stars * 2.0 * mask >= ORB_CUTOFF
    rgba = np.zeros(stars.shape + (4,), np.uint8)
    rgba[..., 3] = keep * 255
    return dict(texture=0x809F8016, kind="decal", approx=ORB_NOTE, image=Image.fromarray(rgba, "RGBA"))
