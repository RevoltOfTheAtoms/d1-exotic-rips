# D1 Exotic Rips

Rip every exotic weapon from **your own Destiny 1 (PS4) game dump** and browse them in a website, as 3D models you can
spin, rendered with the game's own shaders. Point it at your dump, press **Build**, and you get a ready-to-host website
with all 95 exotic weapons: models, textures, dyes, stats, perks and lore.

> This repository contains **no game assets**. Everything is extracted from a dump you provide.

## What you need

| | |
|---|---|
| **Your Destiny 1 PS4 dump** | the disc (`CUSA00568` or your region's) and the final **1.33 patch**, each with its `packages/` folder |
| **Python 3.10 or newer** | from [python.org](https://www.python.org/downloads/) (on Windows, tick "Add python.exe to PATH") |
| **`oo2core_3_win64.dll`** | the Oodle decompressor: see [The Oodle DLL](#the-oodle-dll) |
| **A Bungie API key** | free, from [bungie.net/en/Application](https://www.bungie.net/en/Application): used only while building |

Runs on **Windows** and **x86-64 Linux**.

## Quick start

1. Download this project.
2. **Windows:** double-click `start.bat`. **Linux:** run `./start.sh`.
3. In the window:
   1. **Your Destiny 1 dump**: press *Find automatically*, or *Browse* to the disc and patch folders.
   2. **Oodle decompressor**: *Browse* to `oo2core_3_win64.dll`.
   3. **Bungie API key**: paste it and press *Test key*.
   4. **Build**: press *Build*. The first build takes about 20–30 minutes.
4. Press **Open website**.

Everything you enter is remembered (`d1rip.settings.json`, and the key in `.secrets/`), so next time it's just *Build*.
Building again only exports weapons that aren't built yet; choose *Rebuild everything* after updating the project.

## Prefer the command line?

Everything the window does is also a command (on Linux, `python3` instead of `py`):

```
py d1rip.py setup --api-key YOUR_KEY      # finds your dump and the Oodle DLL, saves them
py d1rip.py build                         # builds everything
py d1rip.py serve                         # opens the website at http://localhost:8765/
```

| Command | What it does |
|---|---|
| `py d1rip.py` | opens the window (same as `gui`) |
| `py d1rip.py setup` | finds your dump and the Oodle DLL and saves them; set them yourself with `--disc DIR`, `--patch DIR`, `--oodle FILE`, `--api-key KEY` |
| `py d1rip.py check` | shows what's set up and what's missing |
| `py d1rip.py build` | item text from Bungie, every weapon, the website (`--rebuild` re-exports everything) |
| `py d1rip.py serve` | opens the website locally (`--port` to change the port) |
| `py d1rip.py list` | the exotic weapons your dump has models for |
| `py d1rip.py export "Thorn"` | exports single weapons by name or item hash |
| `py d1rip.py site` | rebuilds just the website from the exports |

The first time, install the two Python packages with `py -m pip install -r requirements.txt` (the launchers and
`setup` do this for you).

## The Oodle DLL

Destiny 1's packages are compressed with an old version of RAD Game Tools' Oodle, and only `oo2core_3_win64.dll` can
decompress them, as the [tiger-pkg README](https://github.com/v4nguard/tiger-pkg/blob/main/README.md) explains. It's
proprietary, so it can't be included here. Destiny 2 and Marathon installations keep their Oodle DLLs in `bin\x64`;
copy `oo2core_3_win64.dll` from there (it must be version **3**: `oo2core_9` won't work for Destiny 1). Put it at
`oodle/oo2core_3_win64.dll`, or point the window's *Browse* button at it, which copies it there for you.

This project never opens other games' folders by itself. You copy the DLL across.

### Linux

As in tiger-pkg, Linux uses **liblinoodle**, a small library that runs the same Windows DLL inside a Linux program. The
build downloads `liblinoodle3.so` from the tiger-pkg repository and checks it against a pinned checksum. You still need
`oo2core_3_win64.dll` next to it in `oodle/`. Linux needs an x86-64 CPU. If the window doesn't open, install tkinter
(`sudo apt install python3-tk` on Ubuntu/Debian) or use the command line.


## The Bungie API key

The weapon names, perk descriptions and lore aren't in the game files: Destiny downloads them from Bungie. The build
fetches a fresh copy of Bungie's Destiny 1 manifest with your key, and only downloads again when Bungie's version
changes. The key is used **only while building**: the finished website contains the text it needs and never contains or
needs the key. It's stored in `.secrets/bungie_api_key.txt`, which is never committed.

## What you get

| Folder | Contents |
|---|---|
| `preview_133/` | the finished website: static files, host it with any web server |
| `export_133/` | one folder per weapon: `.glb` model (opens in Blender), raw textures, shader binaries, material data, report |

To host the website, copy `preview_133/` to any web server (nginx, Apache, Caddy, ...). It needs no internet
connection: its libraries are bundled. The server only has to send `.glb` files as `model/gltf-binary` and `.js` files
as `text/javascript`. It contains Bungie's game assets extracted from your dump, so keep it private.

## Project layout

```
start.bat / start.sh    double-click launchers (Windows / Linux)
d1rip.py                the command line (and `d1rip.py gui`)
d1kit/                  the Python package that does the work
  gui.py                  the window
  pipeline.py             the build, step by step (shared by the window and the command line)
  setup.py  locate.py     finding and checking your dump, Oodle and key
  manifest.py             Bungie's item text (needs the API key)
  config.py               paths and settings
  pkg/                    reading Destiny's package files
  textures/               decoding PS4 textures
  gpu/                    running the game's PS4 shaders on the CPU
  game/                   weapons, parts, dyes, stats, perks
  export/                 building each weapon's 3D model
  site/                   building the website
frontend/               the website itself: page, game lighting, bundled libraries
tests/                  regression check (exports must stay identical)
research/               reverse-engineering helpers (not needed to use the project)
docs/                   how it works, data formats, research notes
```

## Learn more

- [How it works](docs/HOW_IT_WORKS.md): the pipeline in plain language
- [Data formats](docs/FORMATS.md): what's known about Destiny 1's PS4 files
- [Roadmap](ROADMAP.md): what's planned (armour, character models)
- [Contributing](CONTRIBUTING.md): working on the code

## Credits

- [tiger-pkg](https://github.com/v4nguard/tiger-pkg) (MIT): the reference for Destiny's package format, and
  `liblinoodle3.so` for Linux
- [three.js](https://threejs.org/) (MIT), bundled in `frontend/vendor/`
- Fonts Saira Condensed, IBM Plex Sans and IBM Plex Mono (SIL Open Font License), bundled in `frontend/vendor/fonts/`
- Item text: Bungie's Destiny 1 manifest, via the [Bungie.net API](https://github.com/Bungie-net/api)

## Licence

The project's code is under the [MIT licence](LICENSE). Bundled libraries keep their own licences (see
`frontend/vendor/`). Destiny is a trademark of Bungie. This is an unofficial fan project and is not affiliated with
Bungie; no Bungie assets are included.
