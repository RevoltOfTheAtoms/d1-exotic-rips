"""D1 Exotic Rips: rip every Destiny 1 (PS4) exotic weapon from your own dump into a 3D viewer website.

Run without arguments to open the window. Or use the command line:

    py d1rip.py setup                 find your dump and the Oodle DLL automatically, and save them
    py d1rip.py setup --disc DIR --patch DIR --oodle FILE --api-key KEY      (set any of them yourself)
    py d1rip.py check                 is everything in place?
    py d1rip.py build                 build everything (only weapons not built yet; --rebuild for all)
    py d1rip.py serve                 open the finished website at http://localhost:8765/

    py d1rip.py list                  the exotic weapons your dump has models for
    py d1rip.py export "Thorn" ...    export single weapons by name or item hash
    py d1rip.py site                  rebuild just the website from the exports
    py d1rip.py gui                   open the window

On Linux use python3 instead of py. See README.md.
"""

import argparse
import http.server
import os
import sys
import webbrowser
from functools import partial

from d1kit import config, manifest, pipeline, setup


def cmd_gui(_args):
    try:
        from d1kit.gui import main
    except ImportError as ex:  # tkinter isn't installed (some Linux distributions ship it separately)
        sys.exit(
            f"The window needs tkinter ({ex}). On Ubuntu/Debian: sudo apt install python3-tk\n"
            "Or use the command line: python3 d1rip.py --help"
        )
    main()


def cmd_setup(args):
    setup.install_packages()
    disc, patch, oodle = args.disc, args.patch, args.oodle
    if not (disc and patch and oodle):
        found_disc, found_patch, found_oodle = setup.autodetect()
        disc = disc or (config.DISC_ROOT if setup.inspect_folder(config.DISC_ROOT) else found_disc)
        patch = patch or (config.PATCH_ROOT if setup.inspect_folder(config.PATCH_ROOT) else found_patch)
        oodle = oodle or found_oodle
    try:
        setup.save_paths(disc=disc, patch=patch, oodle=oodle)
        setup.ensure_platform_oodle()
    except setup.SetupError as ex:
        sys.exit(str(ex))
    if args.api_key:
        manifest.save_api_key(args.api_key)
    print()
    problems = setup.check()
    if problems:
        print("\nSet what's missing with: py d1rip.py setup --disc DIR --patch DIR --oodle FILE --api-key KEY")
    return 1 if problems else 0


def cmd_check(_args):
    return 1 if setup.check() else 0


def cmd_build(args):
    try:
        failed = pipeline.run_build(rebuild=args.rebuild)
    except pipeline.BuildError as ex:
        sys.exit(f"\nBuild stopped: {ex}\nRun 'py d1rip.py setup' (or the window) to fix it.")
    print("Open it with: py d1rip.py serve")
    return 1 if failed else 0


def cmd_list(_args):
    from d1kit.export.batch import exotic_weapons, print_list

    print_list(exotic_weapons())


def cmd_export(args):
    from d1kit.export.weapon import export

    for item in args.items:
        export(item, keep_effects=args.keep_effects)


def cmd_site(_args):
    gone = setup.missing_viewer_images()
    if gone:
        sys.exit(f"Missing website images ({', '.join(gone)}). Run: py d1rip.py build")
    from d1kit.site.build import build_site

    build_site()


def cmd_serve(args):
    if not os.path.isfile(os.path.join(config.SITE_DIR, "index.html")):
        sys.exit("No website yet. Run: py d1rip.py build")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=config.SITE_DIR)
    handler.extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".glb": "model/gltf-binary",
        ".js": "text/javascript",
    }
    url = f"http://localhost:{args.port}/"
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Serving the website at {url}  (Ctrl+C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def main():
    if len(sys.argv) == 1:
        return cmd_gui(None)
    p = argparse.ArgumentParser(prog="d1rip", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    sub.add_parser("gui", help="open the window").set_defaults(fn=cmd_gui)

    s = sub.add_parser("setup", help="find or set the dump, Oodle DLL and API key")
    s.add_argument("--disc", metavar="DIR", help="your disc dump folder (holds packages/)")
    s.add_argument("--patch", metavar="DIR", help="your 1.33 patch dump folder")
    s.add_argument("--oodle", metavar="FILE", help="path to oo2core_3_win64.dll")
    s.add_argument("--api-key", metavar="KEY", help="your Bungie API key (bungie.net/en/Application)")
    s.set_defaults(fn=cmd_setup)

    sub.add_parser("check", help="check the setup").set_defaults(fn=cmd_check)

    s = sub.add_parser("build", help="build everything: item text, weapons, website")
    s.add_argument("--rebuild", action="store_true", help="export every weapon again, not just missing ones")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("serve", help="open the website locally")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("list", help="list exportable exotic weapons").set_defaults(fn=cmd_list)

    s = sub.add_parser("export", help="export single weapons (one folder each in export_133/)")
    s.add_argument("items", nargs="+", help='weapon names or item hashes, e.g. "Thorn" 3164616404')
    s.add_argument("--keep-effects", action="store_true", help="also keep smoke / holo effect passes")
    s.set_defaults(fn=cmd_export)

    sub.add_parser("site", help="rebuild just the website from the exports").set_defaults(fn=cmd_site)

    args = p.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
