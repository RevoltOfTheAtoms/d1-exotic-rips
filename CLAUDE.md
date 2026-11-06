# CLAUDE.md

Guidance for AI agents working in this repository. Humans: see README.md and CONTRIBUTING.md.

## What this is

A pipeline that rips Destiny 1 (PS4) exotic weapons from the user's own game dump and builds a static website to view
them. Entry points: `start.bat` / `start.sh` (the window), `d1rip.py` (command line; no arguments opens the window).
Code: the `d1kit/` package. Website: `frontend/`. See `docs/HOW_IT_WORKS.md` for the pipeline, `docs/FORMATS.md` for the
file formats and `ROADMAP.md` for what's planned (armour and characters next: keep shared code general).

Supported: Windows and x86-64 Linux. Nothing else.

## Hard rules

- **The dump is read-only.** Never write to the disc or patch dump folders (`CUSA00568/`, `CUSA00568-patch/`, or
  wherever `D1_DISC` / `D1_PATCH` point).
- **Stay inside Destiny 1 data.** Never read, load or copy anything from other games or installs (Destiny 2, Steam
  folders, ...). Only Destiny 1 PS4 data is in scope. If a tool seems to need something from elsewhere, ask first.
  The project's own code follows this too: `d1kit/locate.py` skips game and Steam folders by name. The README tells
  users to copy the Oodle DLL out of their own Destiny 2/Marathon install themselves; the tool never goes looking there.
- **No game assets in git.** Exports, built sites, ripped images, the Oodle DLL, downloaded reference data and analysis
  dumps are all ignored (`.gitignore`). Check `git status` before committing; never force-add ignored files.
- **Secrets**: `.secrets/bungie_api_key.txt` (the Bungie API key) is never printed, logged or committed. The key is
  required to build (it fetches Bungie's manifest, `d1kit/manifest.py`) and is never written into the website.
  `d1rip.settings.json` (saved paths) is also local only.
- **Organic data only.** Values come from the game files. Don't invent, normalise or "fix up" colours or strengths. When
  the game sets a value at runtime (stored as 0), keep it flagged and show a neutral default. Any deliberate exception
  goes in `d1kit/export/overrides.py` with its reason, and is flagged in the output (`d1Approx`, ...), and only when the
  user asks for it.
- **Tools**: write your own or use well-known FOSS. Don't download unknown binaries.

## Layout

- `d1kit/config.py`: every path and setting: env vars `D1_DISC`, `D1_PATCH`, `D1_OODLE`, `D1_BUILD` override
  `d1rip.settings.json`, which overrides the default layout. Paths can change at runtime (`config.reload()`), so read
  them as `config.X` at call time rather than importing the values.
- `d1kit/gui.py` (tkinter window), `d1kit/pipeline.py` (the build steps, shared by window and CLI),
  `d1kit/setup.py` (paths, Oodle, checks), `d1kit/locate.py` (auto-detect dump and DLL), `d1kit/manifest.py` (Bungie).
- `d1kit/pkg/`: Tiger packages (`package.py`, including the Oodle loader: Windows DLL, or `liblinoodle3.so` on Linux
  as in tiger-pkg), newest-patch lookup and investment tables (`store.py`), tag ids (`tags.py`).
- `d1kit/textures/`: GNM texture headers, detiling and decoding, environment cube atlases.
- `d1kit/gpu/`: GCN disassembler, CPU emulator for PS4 pixel shaders, shader baking.
- `d1kit/game/`: gear-art lookups, dyes, stats, perks and icons.
- `d1kit/export/`: one weapon -> GLB. `weapon.py` orchestrates; `mesh.py`, `materials.py`, `specials.py`,
  `canvas.py`, `gltf.py`; `overrides.py` holds all per-weapon exceptions; `batch.py` exports every exotic.
- `d1kit/site/`: website build (`build.py`) and the images it rips from the dump (`viewer_assets.py`).
- `frontend/`: the website (page template, `d1light.js` game lighting, QA `sheet.html`, vendored three.js and fonts).
- `research/`: standalone reverse-engineering scripts, not used by the pipeline.

## Working on the code

- Run things through the CLI: `py d1rip.py check | setup | build | list | export ... | site | serve`.
- **Regression check before and after any change to export code**: exports are deterministic, so
  `py tests/regression.py save <dir>` before and `py tests/regression.py compare <dir>` after must report 0 differences,
  unless the change is meant to alter output. Then say which weapons changed and why. Against a baseline made on
  another OS, add `--tolerance 1` (NumPy rounding differs by at most 1 in rare texels).
- Lint: `py -m ruff check .` and `py -m ruff format .` (settings in `pyproject.toml`).
- Verify visual changes in the website (`py d1rip.py site` then `serve`), and use `frontend/sheet.html?slugs=a,b` to
  compare several weapons at once. Compare against in-game references the user provides.
- Imports are absolute (`from d1kit.export.mesh import ...`). Keep modules focused; put new per-weapon exceptions in
  `overrides.py`, not inline.
- A full export of all 95 weapons takes about 15 minutes: run it in the background.
