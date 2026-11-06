"""Find every exotic weapon with a model on the current build and export them all.

Exotic = tier byte 5 and a weapon slot (2/3/4) in the item definition, with gear art on this build (its own, or the
same-named raid weapon's for the Adept / ((NAME~)) items: see gear.shared_raid_art).
"""

import os
import time
import traceback

from d1kit.config import EXPORT_DIR, ITEM_HASH_OFF
from d1kit.export.weapon import export
from d1kit.game.gear import art_index_for, item_name, items
from d1kit.game.items import _defs


def exotic_weapons():
    """[{hash, name, type, slot}] sorted by gear slot, type and name."""
    rows = []
    for h, d in _defs().items():
        if d[ITEM_HASH_OFF + 0x12] == 5 and d[ITEM_HASH_OFF + 0x10] in (2, 3, 4) and art_index_for(h)[0] is not None:
            it = items().get(str(h), {"itemHash": h})
            rows.append(
                dict(
                    hash=h,
                    name=item_name(dict(it, itemHash=h)),
                    type=it.get("itemTypeName"),
                    slot=d[ITEM_HASH_OFF + 0x10],
                )
            )
    rows.sort(key=lambda r: (r["slot"], r["type"] or "", r["name"]))
    return rows


def print_list(rows):
    for i, r in enumerate(rows, 1):
        print(f"  {i:>3}  {r['hash']:>10}  {r['type'] or '?':<16} {r['name']}")
    print(f"{len(rows)} exotic weapons with models")


def is_exported(row, out_root=EXPORT_DIR):
    """True when the weapon already has a finished export (its GLB and report) in out_root."""
    from d1kit.export.weapon import slug_for
    from d1kit.game.gear import find_item

    slug = slug_for(find_item(str(row["hash"])))
    folder = os.path.join(out_root, slug)
    return os.path.isfile(os.path.join(folder, "export_report.json")) and os.path.isfile(os.path.join(folder, f"{slug}.glb"))


def export_all(start=1, only=None, out_root=EXPORT_DIR, skip_existing=False, progress=None, stop=None):
    """Export every exotic (from row `start`, 1-based; or just the item hashes in `only`). A failed weapon is retried
    once; returns the rows that still failed.
    skip_existing: leave weapons that already have an export alone (resume after an interrupted build).
    progress(done, total, name): called as each weapon starts. stop(): return True to stop after the current weapon."""
    rows = exotic_weapons()
    failed = []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        if i < start or (only and str(r["hash"]) not in only):
            continue
        if stop and stop():
            print("stopped", flush=True)
            break
        if progress:
            progress(i - 1, len(rows), r["name"])
        if skip_existing and is_exported(r, out_root):
            print(f"[{i}/{len(rows)}] {r['name']}: already exported, skipped", flush=True)
            continue
        for attempt in (1, 2):
            try:
                export(str(r["hash"]), out_root)
                break
            except BaseException as ex:  # export() uses SystemExit for "not found"
                print(f"!! {r['name']} ({r['hash']}) attempt {attempt}: {ex!r}", flush=True)
                if attempt == 2:
                    traceback.print_exc()
                    failed.append(r)
        print(f"[{i}/{len(rows)}] {time.time() - t0:.0f}s", flush=True)
    if progress:
        progress(len(rows), len(rows), "")
    print("FAILED:", [(r["name"], r["hash"]) for r in failed] or "none", flush=True)
    return failed
