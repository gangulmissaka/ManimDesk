# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
"""The "Install Requirements" window: choose a folder, review, install."""

from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk
from typing import Callable

from .environment import (
    PYTHON_VERSION,
    Environment,
    InstallCancelled,
    InstallError,
    Installer,
    build_tools_command,
    default_install_dir,
    is_tex_safe,
)

LOG_BG = "#1e1e24"
LOG_FG = "#e6e6e6"


class InstallerWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        on_installed: Callable[[Environment], None],
        current: Environment | None = None,
    ):
        super().__init__(master)
        self.title("Install Requirements")
        self.geometry("660x500")
        self.minsize(560, 440)
        self.transient(master)

        self.on_installed = on_installed
        start = current.root if current and current.root else default_install_dir()
        self.folder_var = tk.StringVar(value=str(start))
        self.latex_var = tk.BooleanVar(value=True)
        self.events: queue.Queue = queue.Queue()
        self.installer: Installer | None = None
        self.running = False

        self.heading = font.nametofont("TkDefaultFont").copy()
        self.heading.configure(size=12, weight="bold")
        self.mono = font.nametofont("TkFixedFont").copy()
        self.mono.configure(size=9)

        self.body = ttk.Frame(self, padding=(18, 16, 18, 8))
        self.body.pack(fill=tk.BOTH, expand=True)
        ttk.Separator(self).pack(fill=tk.X)
        self.buttons = ttk.Frame(self, padding=(18, 10))
        self.buttons.pack(fill=tk.X)

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.show_location()
        self.grab_set()

    # ---------- pages ----------

    def _page(self, title: str):
        for frame in (self.body, self.buttons):
            for child in frame.winfo_children():
                child.destroy()
        self.title_label = ttk.Label(self.body, text=title, font=self.heading)
        self.title_label.pack(anchor="w", pady=(0, 10))

    def _text(self, parent, text: str, **pack):
        label = ttk.Label(parent, text=text, wraplength=600, justify=tk.LEFT)
        label.pack(anchor="w", **({"pady": (0, 8)} | pack))
        return label

    def _button(self, text: str, command, side=tk.RIGHT, **kw) -> ttk.Button:
        button = ttk.Button(self.buttons, text=text, command=command, **kw)
        button.pack(side=side, padx=(6, 0))
        return button

    def show_location(self):
        self._page("Where should the requirements be installed?")
        self._text(
            self.body,
            "ManimDesk needs Python, Manim and LaTeX to make videos. They'll be downloaded "
            "and kept together in one folder, separate from anything else on your computer.",
        )
        self._text(self.body, "You'll need an internet connection and about 1 GB of free space.")

        row = ttk.Frame(self.body)
        row.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(row, text="Install folder:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.folder_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(row, text="Browse…", command=self.browse).pack(side=tk.LEFT)

        self._text(
            self.body,
            "Videos you make are saved separately, in your Videos folder. "
            "To uninstall the requirements later, delete this folder.",
            pady=(8, 0),
        )

        self._button("Cancel", self.close)
        self._button("Next  ›", self.to_summary, default="active")

    def browse(self):
        current = Path(self.folder_var.get()).expanduser()
        start = current if current.is_dir() else current.parent if current.parent.is_dir() else Path.home()
        path = filedialog.askdirectory(parent=self, initialdir=start, title="Choose install folder")
        if path:
            chosen = Path(path)
            # Picking an existing, unrelated folder: install into a ManimDesk folder inside it.
            if chosen.name.lower() != "manimdesk" and any(chosen.iterdir()):
                chosen = chosen / "ManimDesk"
            self.folder_var.set(str(chosen))

    def folder(self) -> Path:
        return Path(self.folder_var.get().strip()).expanduser()

    def to_summary(self):
        text = self.folder_var.get().strip()
        if not text or not self.folder().is_absolute():
            messagebox.showerror("Choose a folder", "Enter the full path of a folder.", parent=self)
            return
        folder = self.folder()
        if folder.is_file():
            messagebox.showerror("Not a folder", f"{folder} is a file.", parent=self)
            return
        self.show_summary()

    def show_summary(self):
        folder = self.folder()
        self._page("Ready to install")
        self._text(self.body, f"Install folder:  {folder}")

        items = ttk.Frame(self.body)
        items.pack(fill=tk.X, pady=(4, 8))
        for text in (
            f"Python {PYTHON_VERSION}: a private copy just for ManimDesk",
            "Manim, plus NumPy, SciPy, SymPy and Matplotlib for maths and physics",
        ):
            ttk.Label(items, text="✔  " + text).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            items,
            text="LaTeX (TinyTeX): needed for Tex, MathTex and numbered axes",
            variable=self.latex_var,
        ).pack(anchor="w", pady=2)

        system_latex = shutil.which("latex")
        if system_latex:
            self._text(
                self.body,
                f"LaTeX is already installed on this computer ({system_latex}). "
                "You can untick LaTeX to save about 300 MB; ManimDesk will use the existing one.",
            )
        if not is_tex_safe(folder):
            self._text(
                self.body,
                "⚠ This folder's path has spaces or non-English letters, which can stop "
                "LaTeX from working. A folder like C:\\ManimDesk is safer.",
            )

        command = build_tools_command()
        if command:
            box = ttk.LabelFrame(self.body, text="One thing first", padding=10)
            box.pack(fill=tk.X, pady=(4, 0))
            self._text(
                box,
                "Manim needs a few system libraries to build on this computer, and installing "
                "them needs your password. Run this in a terminal, then click Check again:",
            )
            row = ttk.Frame(box)
            row.pack(fill=tk.X)
            entry = ttk.Entry(row)
            entry.insert(0, command)
            entry.configure(state="readonly")
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(row, text="Copy", command=lambda: self._copy(command)).pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ttk.Button(row, text="Check again", command=self.show_summary).pack(
                side=tk.LEFT, padx=(6, 0)
            )

        self._button("Cancel", self.close)
        self._button("Install", self.start_install, default="active")
        self._button("‹  Back", self.show_location)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def show_progress(self):
        self._page("Installing…")
        self.step_var = tk.StringVar(value="Starting…")
        ttk.Label(self.body, textvariable=self.step_var).pack(anchor="w")
        self.bar = ttk.Progressbar(self.body, maximum=1000, mode="determinate")
        self.bar.pack(fill=tk.X, pady=(6, 10))

        frame = ttk.Frame(self.body)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.log = tk.Text(
            frame, height=12, font=self.mono, bg=LOG_BG, fg=LOG_FG, relief=tk.FLAT,
            padx=6, pady=4, wrap=tk.CHAR, state=tk.DISABLED,
        )
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("err", foreground="#ff7b72")

        self.cancel_btn = self._button("Cancel", self.close)

    # ---------- installing ----------

    def start_install(self):
        self.show_progress()
        self.installer = Installer(
            self.folder(),
            with_latex=self.latex_var.get(),
            log=lambda text: self.events.put(("log", text)),
            progress=lambda fraction, label: self.events.put(("progress", (fraction, label))),
        )
        self.running = True
        threading.Thread(target=self._work, daemon=True).start()
        self.after(100, self._poll)

    def _work(self):
        try:
            self.events.put(("done", self.installer.run()))
        except InstallCancelled:
            self.events.put(("cancelled", None))
        except (InstallError, OSError) as e:
            self.events.put(("error", str(e)))
        except Exception as e:  # keep the window usable whatever goes wrong
            self.events.put(("error", f"{type(e).__name__}: {e}"))

    def _write(self, text: str, tag: str | None = None):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._write(value, "err" if "error" in value.lower() else None)
                elif kind == "progress":
                    fraction, label = value
                    self.bar["value"] = fraction * 1000
                    self.step_var.set(label)
                else:
                    self._finished(kind, value)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finished(self, kind: str, value):
        self.running = False
        for child in self.buttons.winfo_children():
            child.destroy()
        if kind == "done":
            self.title_label.configure(text="Installation complete")
            self.bar["value"] = 1000
            self.step_var.set("Everything is installed. You can start making videos.")
            self._write("\n✔ Installation complete.\n", "ok")
            self.on_installed(value)
            self._button("Finish", self.destroy, default="active")
        elif kind == "cancelled":
            self.destroy()
        else:
            self.title_label.configure(text="Installation didn't finish")
            self.step_var.set("Installation failed. Details are below.")
            self._write(f"\n✖ {value}\n", "err")
            self._write("Things already installed are kept, so trying again is quicker.\n")
            self._button("Close", self.destroy)
            self._button("Try again", self.start_install, default="active")

    def close(self):
        if not self.running:
            self.destroy()
            return
        if messagebox.askyesno(
            "Stop installing?",
            "Stop the installation? What's installed so far is kept.",
            parent=self,
        ):
            self.step_var.set("Stopping…")
            self.cancel_btn.configure(state=tk.DISABLED)
            self.installer.cancel()
