"""The D1 Exotic Rips window: point it at your dump, add the Oodle DLL and a Bungie API key, press Build.

Built with tkinter (part of Python), so it needs nothing extra. Everything it does goes through setup.py and
pipeline.py, the same code as the command line.
"""

import http.server
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from functools import partial
from tkinter import filedialog, messagebox, ttk

from d1kit import config, locate, manifest, pipeline, setup

API_KEY_PAGE = "https://www.bungie.net/en/Application"
README_OODLE = "https://github.com/v4nguard/tiger-pkg/blob/main/README.md"
OK, BAD = "✔", "✖"  # check mark, cross


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the built site; no request logging (there may be no console to log to)."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".glb": "model/gltf-binary",
        ".js": "text/javascript",
    }

    def log_message(self, *args):
        pass


class NullWriter:
    """Stands in for stdout/stderr when started without a console (pyw / start.bat)."""

    def write(self, text):
        return len(text)

    def flush(self):
        pass


class QueueWriter:
    """File-like object that sends print() output to the window's log."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("D1 Exotic Rips")
        self.minsize(760, 680)
        self.events = queue.Queue()
        self.worker = None
        self.stop_requested = False
        self.server = None
        self._build_ui()
        self._load_values()
        self.after(100, self._poll)
        if not setup.inspect_folder(self.disc.get()) or not setup.inspect_folder(self.patch.get()):
            self.after(300, self.find_automatically)

    # --- layout ------------------------------------------------------------------------------------------------------

    def _build_ui(self):
        pad = dict(padx=10, pady=4)
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        ttk.Label(root, text="D1 Exotic Rips", font=("Segoe UI", 16, "bold")).grid(sticky="w")
        ttk.Label(
            root, text="Rip every Destiny 1 (PS4) exotic weapon from your own game dump into a 3D viewer website."
        ).grid(sticky="w", pady=(0, 8))

        # 1. dump
        box = ttk.LabelFrame(root, text="1.  Your Destiny 1 dump", padding=8)
        box.grid(sticky="ew", **pad)
        box.columnconfigure(1, weight=1)
        self.disc, self.disc_status = self._path_row(box, 0, "Disc folder", self.browse_disc)
        self.patch, self.patch_status = self._path_row(box, 2, "1.33 patch folder", self.browse_patch)
        ttk.Button(box, text="Find automatically", command=self.find_automatically).grid(
            row=4, column=1, sticky="w", pady=4
        )

        # 2. oodle
        box = ttk.LabelFrame(root, text="2.  Oodle decompressor", padding=8)
        box.grid(sticky="ew", **pad)
        box.columnconfigure(1, weight=1)
        self.oodle, self.oodle_status = self._path_row(box, 0, locate.DLL, self.browse_oodle)
        hint = ttk.Label(
            box,
            text="Not included (proprietary). It comes with Destiny 2 / Marathon installs (bin\x64). Why it's needed",
            foreground="#2a6ab8",
            cursor="hand2",
        )
        hint.grid(row=2, column=1, sticky="w")
        hint.bind("<Button-1>", lambda e: webbrowser.open(README_OODLE))

        # 3. api key
        box = ttk.LabelFrame(root, text="3.  Bungie API key (used only while building)", padding=8)
        box.grid(sticky="ew", **pad)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="API key").grid(row=0, column=0, sticky="w")
        self.api_key = tk.StringVar()
        self.key_entry = ttk.Entry(box, textvariable=self.api_key, show="•")
        self.key_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.show_key = tk.BooleanVar()
        ttk.Checkbutton(box, text="Show", variable=self.show_key, command=self._toggle_key).grid(row=0, column=2)
        ttk.Button(box, text="Test key", command=self.test_key).grid(row=0, column=3, padx=(6, 0))
        self.key_status = ttk.Label(box, text="")
        self.key_status.grid(row=1, column=1, sticky="w")
        link = ttk.Label(
            box,
            text="Get a free key at bungie.net/en/Application. It downloads the item names, perks and lore.",
            foreground="#2a6ab8",
            cursor="hand2",
        )
        link.grid(row=2, column=1, columnspan=3, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(API_KEY_PAGE))

        # 4. build
        box = ttk.LabelFrame(root, text="4.  Build", padding=8)
        box.grid(sticky="nsew", **pad)
        root.rowconfigure(box.grid_info()["row"], weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(4, weight=1)
        self.mode = tk.StringVar(value="missing")
        modes = ttk.Frame(box)
        modes.grid(sticky="w")
        ttk.Radiobutton(modes, text="Only weapons not built yet", variable=self.mode, value="missing").pack(side="left")
        ttk.Radiobutton(modes, text="Rebuild everything", variable=self.mode, value="all").pack(side="left", padx=12)
        buttons = ttk.Frame(box)
        buttons.grid(sticky="w", pady=6)
        self.build_btn = ttk.Button(buttons, text="Build", command=self.build)
        self.build_btn.pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.step_label = ttk.Label(box, text="Ready.")
        self.step_label.grid(sticky="w")
        self.bar = ttk.Progressbar(box, mode="determinate")
        self.bar.grid(sticky="ew", pady=4)
        self.log = tk.Text(box, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(sticky="nsew")
        scroll = ttk.Scrollbar(box, command=self.log.yview)
        scroll.grid(row=4, column=1, sticky="ns")
        self.log["yscrollcommand"] = scroll.set

        # result
        bottom = ttk.Frame(root)
        bottom.grid(sticky="ew", padx=10, pady=(6, 0))
        self.open_btn = ttk.Button(bottom, text="Open website", command=self.open_site)
        self.open_btn.pack(side="left")
        ttk.Button(bottom, text="Open output folder", command=self.open_folder).pack(side="left", padx=6)

    def _path_row(self, box, row, label, browse):
        ttk.Label(box, text=label).grid(row=row, column=0, sticky="w")
        var = tk.StringVar()
        ttk.Entry(box, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(box, text="Browse...", command=browse).grid(row=row, column=2)
        status = ttk.Label(box, text="")
        status.grid(row=row + 1, column=1, sticky="w")
        var.trace_add("write", lambda *a: self._refresh_status())
        return var, status

    # --- values ------------------------------------------------------------------------------------------------------

    def _load_values(self):
        disc, patch, oodle = setup.current_paths()
        self.disc.set(disc)
        self.patch.set(patch)
        self.oodle.set(oodle if os.path.isfile(oodle) else "")
        self.api_key.set(manifest.load_api_key())
        self._refresh_status()

    def _refresh_status(self):
        def show(label, info, kind):
            if info and info[kind]:
                label.config(text=f"{OK}  {setup.describe(info)}", foreground="#1d7a32")
            else:
                label.config(text=f"{BAD}  not a Destiny 1 PS4 {kind} folder yet", foreground="#a33")

        show(self.disc_status, setup.inspect_folder(self.disc.get()), "disc")
        show(self.patch_status, setup.inspect_folder(self.patch.get()), "patch")
        dll = self.oodle.get()
        ok = os.path.isfile(dll) and os.path.basename(dll).lower() == locate.DLL
        self.oodle_status.config(
            text=f"{OK}  found" if ok else f"{BAD}  not set", foreground="#1d7a32" if ok else "#a33"
        )

    def _toggle_key(self):
        self.key_entry.config(show="" if self.show_key.get() else "•")

    def browse_disc(self):
        d = filedialog.askdirectory(title="Your Destiny 1 disc dump (the folder holding packages/)")
        if d:
            self.disc.set(d)

    def browse_patch(self):
        d = filedialog.askdirectory(title="Your Destiny 1 1.33 patch (the folder holding packages/)")
        if d:
            self.patch.set(d)

    def browse_oodle(self):
        f = filedialog.askopenfilename(title=f"Find {locate.DLL}", filetypes=[("Oodle DLL", locate.DLL), ("All", "*")])
        if f:
            self.oodle.set(f)

    def find_automatically(self):
        self.step_label.config(text="Looking for your dump and the Oodle DLL...")
        self.update_idletasks()
        disc, patch, oodle = setup.autodetect(log=lambda *a: None)
        if disc:
            self.disc.set(disc)
        if patch:
            self.patch.set(patch)
        if oodle:
            self.oodle.set(oodle)
        found = [n for n, v in (("disc", disc), ("patch", patch), ("Oodle DLL", oodle)) if v]
        missing = [n for n, v in (("disc", disc), ("patch", patch), ("Oodle DLL", oodle)) if not v]
        msg = ("Found: " + ", ".join(found) + ". ") if found else ""
        msg += ("Use Browse for: " + ", ".join(missing) + ".") if missing else "Everything found."
        self.step_label.config(text=msg)

    def test_key(self):
        self.key_status.config(text="checking...", foreground="")
        self.update_idletasks()
        try:
            manifest.check_key(self.api_key.get().strip())
            self.key_status.config(text=f"{OK}  Bungie accepted the key", foreground="#1d7a32")
        except manifest.ManifestError as ex:
            self.key_status.config(text=f"{BAD}  {ex}", foreground="#a33")

    def _save(self):
        """Save the paths and key; returns an error message or None."""
        try:
            setup.save_paths(disc=self.disc.get(), patch=self.patch.get(), oodle=self.oodle.get())
        except setup.SetupError as ex:
            return str(ex)
        key = self.api_key.get().strip()
        if not key:
            return "Add your Bungie API key (step 3). It's free: bungie.net/en/Application."
        manifest.save_api_key(key)
        return None

    # --- build -------------------------------------------------------------------------------------------------------

    def build(self):
        error = self._save()
        if error:
            messagebox.showwarning("D1 Exotic Rips", error)
            return
        self._clear_log()
        self.stop_requested = False
        self.build_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.bar.config(value=0, maximum=len(pipeline.STEPS))
        rebuild = self.mode.get() == "all"
        self.worker = threading.Thread(target=self._run_build, args=(rebuild,), daemon=True)
        self.worker.start()

    def _run_build(self, rebuild):
        out, err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self.events)
        try:
            failed = pipeline.run_build(
                rebuild=rebuild,
                log=print,
                step=lambda i, name: self.events.put(("step", (i, name))),
                progress=lambda done, total, name: self.events.put(("progress", (done, total, name))),
                stop=lambda: self.stop_requested,
            )
            self.events.put(("done", failed))
        except pipeline.BuildError as ex:
            self.events.put(("error", str(ex)))
        except Exception as ex:  # unexpected: show it rather than die silently
            import traceback

            traceback.print_exc()
            self.events.put(("error", f"{ex.__class__.__name__}: {ex}"))
        finally:
            sys.stdout, sys.stderr = out, err

    def stop(self):
        self.stop_requested = True
        self.stop_btn.config(state="disabled")
        self.step_label.config(text="Stopping after the current weapon...")

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._append(data)
                elif kind == "step":
                    i, name = data
                    self.step_label.config(text=f"Step {i + 1} of {len(pipeline.STEPS)}: {name}")
                    if i != 3:
                        self.bar.config(mode="determinate", maximum=len(pipeline.STEPS), value=i)
                elif kind == "progress":
                    done, total, name = data
                    self.bar.config(maximum=total, value=done)
                    if name:
                        self.step_label.config(
                            text=f"Step 4 of {len(pipeline.STEPS)}: weapon {done + 1} of {total}: {name}"
                        )
                elif kind == "done":
                    self._finish()
                    failed = data
                    if self.stop_requested:
                        self.step_label.config(text="Stopped. Press Build to carry on where it left off.")
                    elif failed:
                        self.step_label.config(text=f"Done, but {len(failed)} weapon(s) failed: see the log.")
                    else:
                        self.bar.config(maximum=1, value=1)
                        self.step_label.config(text="Done! Press Open website.")
                elif kind == "error":
                    self._finish()
                    self.step_label.config(text="Stopped: something needs fixing.")
                    self._append(f"\n{BAD} {data}\n")
                    messagebox.showwarning("D1 Exotic Rips", data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self):
        self.build_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _append(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # --- results -----------------------------------------------------------------------------------------------------

    def open_site(self):
        if not os.path.isfile(os.path.join(config.SITE_DIR, "index.html")):
            messagebox.showinfo("D1 Exotic Rips", "There's no website yet. Press Build first.")
            return
        if self.server is None:
            handler = partial(QuietHandler, directory=config.SITE_DIR)
            self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)  # any free port
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        webbrowser.open(f"http://localhost:{self.server.server_address[1]}/")

    def open_folder(self):
        folder = config.SITE_DIR if os.path.isdir(config.SITE_DIR) else config.WORK
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])


def main():
    if sys.stdout is None:  # started without a console (pyw)
        sys.stdout = NullWriter()
    if sys.stderr is None:
        sys.stderr = NullWriter()
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    App().mainloop()
