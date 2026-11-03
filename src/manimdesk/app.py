# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
"""ManimDesk main window."""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from . import __version__
from .core import (
    ALL_SCENES,
    ASPECTS,
    QUALITIES,
    RenderJob,
    clean_log_line,
    error_summary,
    find_scenes,
    new_videos,
    open_path,
    prepare_render,
    pretty_path,
    resolution,
    start_render,
)
from .environment import (
    Environment,
    active_environment,
    default_video_dir,
    default_workspace,
    kill_tree,
)
from .installer import InstallerWindow

SAMPLE_SCRIPT = '''from manim import *


class HelloManim(Scene):
    def construct(self):
        title = Tex("Hello, Manim!").scale(1.5)
        eq = MathTex(r"e^{i\\pi} + 1 = 0").next_to(title, DOWN, buff=0.8)
        self.play(Write(title))
        self.play(FadeIn(eq, shift=UP))
        self.play(Circumscribe(eq))
        self.wait()
'''

EDITOR_BG = "#1e1e24"
EDITOR_FG = "#e6e6e6"
MOD = "Command" if sys.platform == "darwin" else "Control"


class ManimDesk(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"ManimDesk {__version__}")
        self.geometry("1200x780")
        self.minsize(900, 580)

        self.env: Environment | None = active_environment()
        self.process = None
        self.job: RenderJob | None = None
        self.render_start = 0.0
        self.log_queue: queue.Queue = queue.Queue()
        self.last_videos: list[Path] = []
        self._scan_job = None

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        # clam's default bar is almost the same grey as its trough.
        style.configure("Horizontal.TProgressbar", background="#3b82f6", troughcolor="#e4e4e4")
        self.mono = font.nametofont("TkFixedFont").copy()
        self.mono.configure(size=11)
        self.heading = font.nametofont("TkDefaultFont").copy()
        self.heading.configure(size=11, weight="bold")

        self._build_ui()
        self.editor.insert("1.0", SAMPLE_SCRIPT)
        self.editor.edit_reset()
        self.refresh_scenes()
        self._show_env()
        if self.env is None:
            self.log_write(
                "Welcome to ManimDesk!\n\n"
                "Before making your first video, click\n"
                "\"Install Requirements…\" to download\n"
                "Python, Manim and LaTeX.\n",
                "warn",
            )
        self.after(100, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- layout ----------

    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # Script editor
        bar = ttk.Frame(left)
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Python script", font=self.heading).pack(side=tk.LEFT)
        ttk.Button(bar, text="Clear", command=self.clear_script).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Paste", command=self.paste_script).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="Save…", command=self.save_script).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Open…", command=self.open_script).pack(side=tk.RIGHT, padx=4)

        self.editor = self._scrolled_text(left, undo=True)
        self.editor.master.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        self.editor.bind("<Tab>", self._insert_tab)
        self.editor.bind(f"<{MOD}-a>", self._select_all)
        self.editor.bind("<<Modified>>", self._on_edit)

        # Output settings
        opts = ttk.LabelFrame(left, text="Output video", padding=10)
        opts.pack(fill=tk.X)
        opts.columnconfigure(3, weight=1)

        ttk.Label(opts, text="Scene:").grid(row=0, column=0, sticky="w", pady=3)
        self.scene_var = tk.StringVar()
        self.scene_box = ttk.Combobox(opts, textvariable=self.scene_var, state="readonly")
        self.scene_box.grid(row=0, column=1, columnspan=4, sticky="ew", pady=3)

        ttk.Label(opts, text="Quality:").grid(row=1, column=0, sticky="w", pady=3)
        self.quality_var = tk.StringVar(value=list(QUALITIES)[1])
        choices = ttk.Frame(opts)
        choices.grid(row=1, column=1, columnspan=4, sticky="w")
        for label in QUALITIES:
            ttk.Radiobutton(choices, text=label, value=label, variable=self.quality_var).pack(
                side=tk.LEFT, padx=(0, 12)
            )

        ttk.Label(opts, text="Aspect ratio:").grid(row=2, column=0, sticky="w", pady=3)
        self.aspect_var = tk.StringVar(value=ASPECTS[0])
        choices = ttk.Frame(opts)
        choices.grid(row=2, column=1, columnspan=4, sticky="w")
        for label in ASPECTS:
            ttk.Radiobutton(choices, text=label, value=label, variable=self.aspect_var).pack(
                side=tk.LEFT, padx=(0, 12)
            )

        ttk.Label(opts, text="Save to:").grid(row=3, column=0, sticky="w", pady=3)
        self.output_var = tk.StringVar(value=pretty_path(default_video_dir()))
        ttk.Entry(opts, textvariable=self.output_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", pady=3
        )
        ttk.Button(opts, text="Browse…", command=self.choose_output).grid(
            row=3, column=4, padx=(6, 0), sticky="ew"
        )

        ttk.Label(opts, text="Requirements:").grid(row=4, column=0, sticky="w", pady=3)
        self.env_var = tk.StringVar()
        self.env_label = ttk.Label(opts, textvariable=self.env_var)
        self.env_label.grid(row=4, column=1, columnspan=3, sticky="w", pady=3)
        self.install_btn = ttk.Button(
            opts, text="Install Requirements…", command=self.open_installer
        )
        self.install_btn.grid(row=4, column=4, padx=(6, 0), sticky="ew")

        btns = ttk.Frame(opts)
        btns.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        self.render_btn = ttk.Button(btns, text="▶  Render", command=self.render)
        self.render_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(btns, text="■  Stop", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=6)
        # Shown only while rendering.
        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=160)

        # Log / output
        ttk.Label(right, text="Render log", font=self.heading).pack(anchor="w")
        self.log = self._scrolled_text(right, state=tk.DISABLED)
        self.log.master.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        self.log.tag_configure("err", foreground="#ff7b72")
        self.log.tag_configure("warn", foreground="#e3b341")
        self.log.tag_configure("ok", foreground="#7ee787")

        out = ttk.Frame(right)
        out.pack(fill=tk.X)
        self.open_video_btn = ttk.Button(
            out, text="Open video", command=self.open_video, state=tk.DISABLED
        )
        self.open_video_btn.pack(side=tk.LEFT)
        ttk.Button(out, text="Open output folder", command=self.open_folder).pack(
            side=tk.LEFT, padx=6
        )
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(right, textvariable=self.status_var).pack(anchor="w", pady=(6, 0))

    def _scrolled_text(self, parent, **kw) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(
            frame,
            font=self.mono,
            bg=EDITOR_BG,
            fg=EDITOR_FG,
            insertbackground=EDITOR_FG,
            selectbackground="#3a4a6b",
            relief=tk.FLAT,
            padx=8,
            pady=6,
            wrap=kw.pop("wrap", tk.NONE),
            **kw,
        )
        ys = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        xs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        return text

    # ---------- editor helpers ----------

    def _insert_tab(self, _event):
        self.editor.insert(tk.INSERT, "    ")
        return "break"

    def _select_all(self, _event):
        self.editor.tag_add(tk.SEL, "1.0", tk.END)
        return "break"

    def _on_edit(self, _event):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if self._scan_job:
                self.after_cancel(self._scan_job)
            self._scan_job = self.after(500, self.refresh_scenes)

    def get_script(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def set_script(self, text: str):
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)

    def refresh_scenes(self):
        self._scan_job = None
        try:
            scenes = find_scenes(self.get_script())
        except SyntaxError as e:
            self.status_var.set(f"Syntax error on line {e.lineno}: {e.msg}")
            return
        values = scenes + ([ALL_SCENES] if len(scenes) > 1 else [])
        self.scene_box["values"] = values
        if self.scene_var.get() not in values:
            self.scene_var.set(values[0] if values else "")
        if not self.process:
            self.status_var.set(
                f"Found {len(scenes)} scene(s)" if scenes else "No Scene classes found"
            )

    def open_script(self):
        path = filedialog.askopenfilename(filetypes=[("Python", "*.py"), ("All files", "*")])
        if path:
            self.set_script(Path(path).read_text(encoding="utf-8"))

    def save_script(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".py", filetypes=[("Python", "*.py")]
        )
        if path:
            Path(path).write_text(self.get_script(), encoding="utf-8")
            self.status_var.set(f"Saved {path}")

    def paste_script(self):
        try:
            self.set_script(self.clipboard_get())
        except tk.TclError:
            pass

    def clear_script(self):
        self.editor.delete("1.0", tk.END)

    def choose_output(self):
        current = Path(self.output_var.get()).expanduser()
        path = filedialog.askdirectory(initialdir=current if current.is_dir() else Path.home())
        if path:
            self.output_var.set(pretty_path(Path(path)))

    # ---------- rendering ----------

    def log_write(self, text: str, tag: str | None = None):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def render(self):
        if self.env is None:
            if messagebox.askyesno(
                "Requirements needed",
                "ManimDesk needs Python, Manim and LaTeX before it can make videos.\n\n"
                "Install them now?",
            ):
                self.open_installer()
            return
        source = self.get_script()
        try:
            scenes = find_scenes(source)
        except SyntaxError as e:
            messagebox.showerror("Syntax error", f"Line {e.lineno}: {e.msg}")
            return
        if not scenes:
            messagebox.showerror(
                "No scene", "The script needs at least one class that extends Scene."
            )
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showerror("No output folder", "Choose where to save the video.")
            return

        w, h, fps = resolution(self.quality_var.get(), self.aspect_var.get().startswith("9:16"))
        self.job = RenderJob(
            script=source,
            scene=self.scene_var.get() or scenes[0],
            width=w,
            height=h,
            fps=fps,
            output_dir=Path(output).expanduser(),
            workspace=self.workspace,
        )
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
            cmd = prepare_render(self.job, str(self.env.python))
        except OSError as e:
            messagebox.showerror("Can't write files", str(e))
            return

        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self.log_write(f"Rendering {self.job.scene} at {w}x{h}, {fps} fps…\n\n")
        if not self.env.has_latex():
            self.log_write(
                "Warning: LaTeX wasn't found. Tex, MathTex and axis numbers need it. "
                "Use Install Requirements… to add it.\n\n",
                "warn",
            )

        self.render_start = time.time()
        self.raw_output: list[str] = []
        self.process = start_render(cmd, cwd=self.workspace, extra_path=self.env.path_dirs())
        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()

        self.render_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.open_video_btn.configure(state=tk.DISABLED)
        self.progress.pack(side=tk.LEFT, padx=6)
        self.progress.start(12)
        self.status_var.set("Rendering…")

    def _read_output(self, proc):
        for line in proc.stdout:
            self.log_queue.put(("line", line))
        self.log_queue.put(("done", proc.wait()))

    def _drain_log(self):
        try:
            while True:
                kind, value = self.log_queue.get_nowait()
                if kind == "line":
                    self.raw_output.append(value)
                    line = clean_log_line(value)
                    if line is not None:
                        bad = "Error" in line or "Traceback" in line
                        self.log_write(line + "\n", "err" if bad else None)
                else:
                    self._finished(value)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _finished(self, code: int):
        self.process = None
        self.progress.stop()
        self.progress.pack_forget()
        self.render_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)

        if code != 0:
            summary = error_summary("".join(self.raw_output))
            self.status_var.set(summary or f"Render failed (exit code {code})")
            self.log_write(f"\nRender failed (exit code {code}).\n", "err")
            if summary:
                self.log_write(summary + "\n", "err")
            return

        self.last_videos = new_videos(self.job.video_dir, self.render_start)
        if self.last_videos:
            self.open_video_btn.configure(state=tk.NORMAL)
            self.status_var.set("Done: " + ", ".join(p.name for p in self.last_videos))
            self.log_write("\n")
            for p in self.last_videos:
                self.log_write(f"✔ Saved {p.name}\n", "ok")
            self.log_write(f"  in {pretty_path(self.job.video_dir)}\n")
        else:
            self.status_var.set("Done (no new video found)")

    def stop(self):
        if self.process:
            kill_tree(self.process)
            self.log_write("\nStopped by user.\n", "err")

    # ---------- requirements ----------

    @property
    def workspace(self) -> Path:
        """Scripts and cache live with the installed requirements, if there are any."""
        if self.env and self.env.root:
            return self.env.root
        return default_workspace()

    def _show_env(self):
        if self.env is None:
            self.env_var.set("✖ Not installed yet")
            self.env_label.configure(foreground="#c0392b")
        elif self.env.root:
            latex = "" if self.env.has_latex() else " (no LaTeX)"
            self.env_var.set(f"✔ Installed in {pretty_path(self.env.root)}{latex}")
            self.env_label.configure(foreground="#2e7d32")
        else:
            self.env_var.set("✔ Using the Manim already installed in this Python")
            self.env_label.configure(foreground="#2e7d32")

    def open_installer(self):
        if self.process:
            messagebox.showinfo("Busy", "Wait for the current render to finish first.")
            return
        InstallerWindow(self, on_installed=self._installed, current=self.env)

    def _installed(self, env: Environment):
        self.env = env
        self._show_env()
        self.log_write(f"\n✔ Requirements installed in {pretty_path(env.root)}.\n", "ok")
        self.status_var.set("Ready to render")

    # ---------- output ----------

    def open_video(self):
        if self.last_videos:
            open_path(self.last_videos[-1])

    def open_folder(self):
        folder = self.job.video_dir if self.job else Path(self.output_var.get()).expanduser()
        while not folder.exists() and folder.parent != folder:
            folder = folder.parent
        open_path(folder)

    def _on_close(self):
        if self.process and not messagebox.askyesno(
            "Quit", "A render is running. Stop it and quit?"
        ):
            return
        if self.process:
            kill_tree(self.process)
        self.destroy()


def main():
    if sys.platform == "win32":
        # Sharp text on high-DPI Windows displays.
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    ManimDesk().mainloop()


if __name__ == "__main__":
    main()
