# Roadmap

## Now: exotic weapons (done)

All 95 exotic weapons from the 1.33 dump, rendered with the game's own shaders, with a desktop window and a command line
on Windows and Linux.

## Next: armour and character models (planned, not started)

The framework was built so these slot in beside the weapons rather than replacing anything.

**Already shared, nothing to change:**

- `d1kit/pkg/`: package reading, patches, tags (armour lives in the same packages, e.g. `ps4_gear_player_*`)
- `d1kit/textures/`: PS4 texture decoding
- `d1kit/gpu/`: the shader emulator. Armour uses gear shaders of the same kind, and the dye block lookup
  (`shader_bake.dye_block_end`) already finds each shader's dye slots by itself
- `d1kit/game/gear.py`, `dyes.py`: gear-art arrangements, part lookups and dyes work for any gear item
- `d1kit/export/mesh.py`, `canvas.py`, `gltf.py`, `materials.py`, `specials.py`: geometry, plate atlases, baking and
  glTF output aren't weapon-specific
- `d1kit/manifest.py`: the manifest already has every item (armour included)
- `tests/regression.py`: add armour pieces to the reference set

**To add:**

1. **Item selection**: `export/batch.py` picks exotic *weapons* (equip slots 2/3/4). Add armour slots (helmet,
   gauntlets, chest, legs, class item) and a way to choose which kinds to build.
2. **Class and gender variants**: armour arrangements differ per class and per body. `gear.arrangement()` returns
   every variant per slot; weapons take the first. Armour needs the right variant per class/gender.
3. **Weapon-only rules**: `export/weapon.py` has a few weapon assumptions (sword crystal tint, sword effect bounds,
   scope lens checks). Move the shared flow into a general `export/gear.py`, keeping `weapon.py` and adding `armor.py`
   for each kind's own rules. Per-item exceptions stay in `overrides.py`.
4. **Character models**: bodies and heads are skinned meshes. That means a skeleton and skinning weights in the glTF,
   which the exporter doesn't write yet, and a way to dress a body in armour pieces.
5. **Website**: browse by category (weapons / armour / characters), class and gender filters.
6. **Window and command line**: a "what to build" choice (`d1rip.py build --armour`, a checkbox in the window).

Keep the project rules: everything from the game files, exceptions only in `overrides.py` and flagged, regression check
around every export change.

## Later / ideas

- Inspect-screen lighting: the game lights gear by the world location and time of day; research notes in
  `docs/research/inspect-lighting.md`.
