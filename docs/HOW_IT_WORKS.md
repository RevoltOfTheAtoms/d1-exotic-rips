# How it works

A plain-language tour of what happens between your PS4 dump and the finished website. For the byte-level details,
see [FORMATS.md](FORMATS.md).

## The big picture

```
your PS4 dump ──► 1. read packages ──► 2. find the weapon's parts ──► 3. build the 3D model
                                                                         │
       website ◄── 6. build the site ◄── 5. write the GLB ◄── 4. paint and shade the textures
```

Everything comes from your own game files. The only outside data is Bungie's Destiny 1 manifest, used for the text
the game doesn't store (weapon names, perk descriptions, lore). The build downloads it with your Bungie API key
(`d1kit/manifest.py`); the finished website has the text written into it and never needs the key.

The window (`d1kit/gui.py`) and the command line (`d1rip.py`) both run the same build (`d1kit/pipeline.py`):
check the dump, fetch the item text, rip the website's images, export the weapons, build the website.

## 1. Reading the game's packages: `d1kit/pkg/`

Destiny keeps its data in about 250 `.pkg` files. Each holds thousands of entries ("tags"), compressed with Oodle.
`package.py` opens a package and decompresses entries, calling the Oodle DLL (on Linux through `liblinoodle3.so`, as
tiger-pkg does). `store.py` finds the newest patched copy
of each package, and `tags.py` turns a tag id like `80aa8380` into "package X, entry Y".

## 2. Finding the weapon: `d1kit/game/`

An item (say Thorn) points at a **gear-art arrangement**, a list of parts per gear slot (barrel, frame, sight, ...).
Each part leads to its meshes and its **plates**: small texture tiles that together make up the gun's texture sheets.
`gear.py` follows those links. `dyes.py` reads the weapon's dyes (its colours), and `items.py` its stats, perks and
icons.

## 3. Building the model: `d1kit/export/mesh.py` and `weapon.py`

Meshes are stored compactly (16-bit positions, triangle strips). `mesh.py` decodes them. `weapon.py` walks every draw
call and decides how it should look:

- **plated surface**: textured from the gun's texture sheets (most of the gun)
- **special**: a decal, a light, a lens or a surface with its own shader (`specials.py`)
- **left out**: shadow passes, smoke and other effects, plus the few exceptions in `overrides.py`

## 4. Painting and shading: `d1kit/export/canvas.py` and `d1kit/gpu/`

The plates are pasted into texture sheets ("canvases") and dyed. Then comes the key step: the game's own **pixel
shaders** decide the final colour. They are compiled PS4 GPU programs, so `gpu/gcn_emu.py` runs them on the CPU
(`gcn_dis.py` reads the GPU instructions, `shader_bake.py` feeds in each pixel's textures and dye). The result is the
colour the game itself would write, plus the reflection strength and gloss the website's lighting uses.

## 5. Writing the model: `d1kit/export/gltf.py`

The model is saved as a `.glb` (standard glTF 3D format) with its textures inside. Each weapon gets a folder in
`export_133/` with the GLB, the raw textures, the shader binaries and a `export_report.json` describing what was found.

## 6. The website: `frontend/` and `d1kit/site/`

`frontend/` is the website: `template.html` (the page), `d1light.js` (the game's lighting, written as a three.js
shader), `sheet.html` (a contact sheet for checking many weapons at once) and `vendor/` (three.js and fonts).
`site/build.py` copies every export into `preview_133/` and fills the page with each weapon's data. The result is plain
static files that any web server can host.

## What isn't "organic"

The project's rule is to use the game's own data and nothing made up. Where the game sets a value only while running
(a glow's brightness, for example), the export shows it at a neutral default and **flags** it in the model file. The
few deliberate exceptions, chosen by comparing with real PS4 screenshots, are all in `d1kit/export/overrides.py` with
their reasons, and the website shows a note on any weapon they affect.
