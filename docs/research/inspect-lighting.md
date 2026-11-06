# Inspect-screen lighting: what the 1.33 eboot shows

Tools: `research/eboot_xref.py` (VA<->file, rip xrefs, call xrefs, relocs, capstone helpers).
eboot: `CUSA00568-patch/eboot.bin` (decrypted ELF; text VA 0 = file 0x4000).

## Chain
- Widget `cui::c_sobject_texture_camera_widget`: vtable 0x19692d0, constructor 0x11aec10, draw 0xaaf580,
  property table built at 0xaafe40 (18 props, 64-bit ids, types 3/0xb).
- Widget draw emits UI draw command opcode 31 -> dispatcher 0x1076900 -> 0x8bc550 (renderer).
- 0x8bc550 builds the light settings block: flags = 0x1a, exposure/scale = 1.0,
  3 lights copied from the command (+0x30..+0x80): per light vec4 colour (w = intensity) + vec4 direction (w = spread).
- 0x8b54a0 -> 0x8b55b0 renders the texture-camera view. If flags & 8: for each of the 3 lights
  colour.xyz * colour.w and direction are projected into an L1 spherical-harmonic ambient (0x808560,
  SH consts 0.28209 / 0.32573) -> applied with 0x808b50. So the inspect lighting is an SH light rig built
  from 3 directional lights, not scene lights (which is why no light objects exist in the packages).

## Widget defaults (constructor 0x11aec10), per light block of 0x50 starting at +0x130
- spread a*b = 0.5 * 1.0, colour = (1,1,1,1) * (1,1,1,1), intensity = 1.0 * 1.0, angles vec = (0,0,0) degrees.
- +0x110 = 60.0 (FOV deg), +0x114 = 1.0.
Real per-screen values are set by the inspect screen's UI data (`inspect_template.cui_screen`, ui_orbit).

## Blocker
UI package entries (type 1/1) decode with long runs of `ff ff ff 00` filler between readable text,
so the property values can't be read yet. Property names in UI data are CamelCase strings
(e.g. StackingDirection); the eboot's 64-bit property ids are not FNV-1a/FNV-1 of those names.
Next: fix UI package decoding (compare block flags / decryption for those blocks), then read the
camera widget's light properties from inspect_template.

## Update 2026-11-05
- The "corrupted" UI entries were not corrupt: type 1/1 entries are UI bitmaps (white, `ff ff ff 00` pixels) whose
  tile padding holds leftover build-tool memory (property-name strings). The package reader is fine.
- UI data does use the eboot's 64-bit class/property ids (e.g. 0x725ad1d887a7707b appears 177x in ui_orbit).
- c_sobject_texture_camera_widget: class id 0xebb17dde28e1c7d6 and its 18 property ids appear in NO entry of
  any package (full dump scan, all non-audio entries, scan_all_ids.py -> scan_all_ids.txt "scan done", no hits).
  The cinematic texture camera widget's ids are absent from UI data too.
- Only those two widgets emit UI draw command 31 (callers of 0x8d2860), so the texture-camera 3-light SH rig is
  not used by any shipped screen data.
- Inspect screen: tag 80aa825e (class 80802dd5, globals_0154), sub-screens 80aa26d7, 80aa8272, 80aa92a2,
  80aa2f11, 80aa2f94; backdrop bitmap 80aa8273 -> texture 80aa8380. No camera widget, almost no floats.
- Lead: string "c_investment_world_tag_loader_fill_desired_items_select_character_view" suggests gear previews
  are loaded into the 3D world ("investment world") and lit by world/scene lighting, not a fixed UI rig.

## Update 2026-11-05 (2): cinematic path
- Inspect screen 80aa825e's widget list includes cui::c_cinematic_bitmap_widget (class 0x30f5fed161b8389b,
  at 0x220 in the tag). Its only property id (0xe0e43831c1212782) is not set in data, so the code picks
  which texture-camera output it shows.
- The cinematic texture camera render (0x8b5970 -> 0x8b5a70) does only clear/stencil state and no SH rig,
  so such a view is lit by whatever lights are in its scene (normal deferred path).
- ui_cinematics_0050: 4 lights, root list 808a0002 = 66 named cinematics (FNV-1a-32 names, per class/race/
  gender: character screens). globals_cinematic_01e3: 1 light, used by travel/activity cinematics.
- globals_0154: 40 lights. The ones next to the inspect screen (80aa8349/834a/8358, point lights r=5/0.4/4)
  belong to class 808005a1 = particle effects (referenced by investment_assets weapon FX), i.e. muzzle
  flash lights, not inspect lighting.
- No data-side inspect light rig found. If the inspect view is a cinematic texture camera, its scene and
  lights are picked in code; tracing that is the remaining (long) route.

## Update 2026-11-05 (3)
- c_cinematic_bitmap_widget (vtable 0x195a020, update 0x9d6eb0) draws the global cinematic render
  (render struct 0x273b8c8; size via 0x8b6c60), i.e. the main 3D "cinematic" view, not a texture camera slot.
  So the inspect weapon is rendered in a real 3D scene and lit by that scene's lights.
- c_cinematic_texture_camera_widget code (0xa9a2c0 -> 0xacc810) feeds character race/gender data:
  character preview, not weapons.
- globals_0154 standalone light pairs (80aa8047/8048, 85ae/85b1, 866e/866f, ...) are used by gear/world entities
  (investment_assets_013e 80800861 entities, observatory activities), not by any inspect scene.
- Remaining route: find in code what scene/camera the cinematic view uses while the inspect screen is up
  and which lights it adds (likely set up in code, no data rig found).

## Tower baked lighting / time-of-day sky (2026-11-05)
- Type 5/1 "raw buffers" in ps4_city_tower_destination_0250 (561, 279 MB) are NOT lighting: they are mip0 pixel data of
  ordinary textures (BC1/3/4/5, RGBA8); type 65/1 entries hold the smaller mips. Headers are 32/1 (60 B). No HDR/BC6
  textures exist in the Tower packages, so there is no lightmap/probe texture set.
- Time-of-day sky table: tag 80ca0b18 (class 80801a50). Texture slots at +0x164 (80ca0e0e..0e1c, 0e15 twice; 0e1d is a
  16x1024 gradient), then 80ca0dec, then 16 key times at +0x1ac (0.032..0.929 of a day). Day length 7200 s (+0x208).
  Each key is a 128x128 RGBA8 sRGB single-mip panorama (sky top, horizon, cloud floor bottom), blurred: night, dawn,
  sunrise, blue midday, sunset, dusk. Renders in analysis/lighting/tower_sky/.
- 80ca0dec (class 80801ba2): 16x32 RGBA8 colour table. 80ca0ded (80801b06): weights 0.75/0.25 + two 1800-sample
  direction curves 80ca0e30/0e31 (class 808007bf; sun/moon paths). 80ca0e1e (80801b5a): more sky params.
- eboot strings: "atmosphere settings", "atmosphere_screenspace_lookup", "c_time_of_day_game_system". The panoramas
  are most likely atmosphere (fog/inscatter) lookups keyed by time of day; use as an object reflection/ambient source
  is NOT verified. Class IDs don't appear as eboot constants.
