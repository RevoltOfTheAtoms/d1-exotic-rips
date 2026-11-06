"""The build, step by step: one routine shared by the window (gui.py) and the command line (d1rip.py build).

1. check the dump and Oodle      (paths saved by setup; a test read of the game files)
2. item text from Bungie         (needs the API key; downloads only when Bungie's version changed)
3. website images                (ripped from the dump, once)
4. export the weapons            (all, or only the ones not exported yet)
5. build the website             (preview_133/)
"""

from d1kit import config, manifest, setup

STEPS = ("Checking your dump", "Item text from Bungie", "Website images", "Exporting weapons", "Building the website")


class BuildError(Exception):
    """The build stopped on something the user can fix; the message says what."""


def run_build(rebuild=False, log=print, step=None, progress=None, stop=None):
    """Run the whole build. rebuild: export every weapon again (otherwise only missing ones).
    log(text): progress messages. step(index, name): a new step starts. progress(done, total, name): weapon export.
    stop(): return True to stop after the current weapon. Returns the list of weapons that failed to export."""

    def begin(i):
        if step:
            step(i, STEPS[i])
        log(f"\n== {i + 1}/{len(STEPS)}  {STEPS[i]}")

    begin(0)
    try:
        setup.install_packages(log)
        setup.ensure_platform_oodle(log)
        problems = [(label, detail) for label, ok, detail in setup.status()[:4] if not ok]
        if problems:
            raise BuildError("Missing: " + "; ".join(f"{label} ({detail})" for label, detail in problems))
        setup.test_read()
        log("  dump and Oodle work")
    except setup.SetupError as ex:
        raise BuildError(str(ex)) from ex

    begin(1)
    try:
        manifest.update(manifest.load_api_key(), log)
    except manifest.ManifestError as ex:
        raise BuildError(str(ex)) from ex

    begin(2)
    if setup.missing_viewer_images():
        from d1kit.site.viewer_assets import rip_viewer_images

        rip_viewer_images()
    else:
        log("  already there")

    begin(3)
    from d1kit.export.batch import export_all

    failed = export_all(skip_existing=not rebuild, progress=progress, stop=stop)
    if stop and stop():
        log("Build stopped. Run it again to carry on where it left off.")
        return failed

    begin(4)
    from d1kit.site.build import build_site

    build_site()
    log(f"\nDone. The website is in {config.SITE_DIR}")
    return failed
