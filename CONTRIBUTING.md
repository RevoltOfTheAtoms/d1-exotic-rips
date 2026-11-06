# Contributing

## Setting up

```
py -m pip install -r requirements.txt
py -m pip install ruff            # linting and formatting
py d1rip.py check                 # needs your own dump and the Oodle DLL (see README)
```

## The golden rule: check your changes against a baseline

Exports are deterministic: the same dump and code give byte-identical files. So for any change to the export code:

```
py tests/regression.py save  ../baseline     # before your change
# ... make the change ...
py tests/regression.py compare ../baseline   # after: lists every file that changed
```

`compare` should say `0 differences` for a refactor. (Comparing against a baseline made on another operating system?
Add `--tolerance 1`: NumPy versions round a few shader results differently.) For a fix, the differences should be exactly the weapons you
meant to change. The reference set (in `tests/regression.py`) covers every special case the exporter handles.

## Style

- `py -m ruff check .` and `py -m ruff format .` before committing (settings in `pyproject.toml`).
- Absolute imports from the package: `from d1kit.export.mesh import triangles`.
- Comments explain *why*, especially anything learned about the game's data. Put file-format knowledge in
  `docs/FORMATS.md` too.
- Keep game data organic: no invented values. A deliberate exception goes in `d1kit/export/overrides.py` with its
  reason, and must be flagged in the output so the website can say so.

## Where things go

| You're changing...                         | Look in                          |
|-------------------------------------------|----------------------------------|
| how packages / tags are read              | `d1kit/pkg/`                     |
| texture decoding                          | `d1kit/textures/`                |
| the shader emulator                       | `d1kit/gpu/`                     |
| which parts / dyes / stats a weapon has   | `d1kit/game/`                    |
| how a draw becomes a glTF material        | `d1kit/export/specials.py`, `gltf.py` |
| a single weapon's special treatment       | `d1kit/export/overrides.py`      |
| the website                               | `frontend/` (page) and `d1kit/site/build.py` (data) |

## Never commit

Game assets or anything made from them (exports, built sites, ripped images), the Oodle DLL, downloaded reference
data, or secrets. `.gitignore` covers all of these; check `git status` before committing.
