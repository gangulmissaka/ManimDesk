# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
"""Render logic for ManimDesk, kept free of GUI code so it can be tested."""

from __future__ import annotations

import ast
import configparser
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# label -> (landscape width, landscape height, fps)
QUALITIES = {
    "480p (15 fps)": (854, 480, 15),
    "720p (30 fps)": (1280, 720, 30),
    "1080p HD (60 fps)": (1920, 1080, 60),
}
ASPECTS = ["16:9 (landscape)", "9:16 (portrait)"]
ALL_SCENES = "<All scenes>"
SCRIPT_NAME = "manimdesk_scene.py"


def default_workspace() -> Path:
    """Folder for scripts, cache and videos. Override with MANIMDESK_HOME."""
    return Path(os.environ.get("MANIMDESK_HOME") or Path.home() / "ManimDesk")


def pretty_path(path: Path) -> str:
    """Show paths inside the home folder as ~/..."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def find_scenes(source: str) -> list[str]:
    """Return names of top-level classes that inherit from something ending in 'Scene'.

    Raises SyntaxError if the source can't be parsed.
    """
    scenes = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            if name.endswith("Scene"):
                scenes.append(node.name)
                break
    return scenes


def resolution(quality: str, portrait: bool) -> tuple[int, int, int]:
    """Return (pixel width, pixel height, fps) for a quality label and orientation."""
    w, h, fps = QUALITIES[quality]
    return (h, w, fps) if portrait else (w, h, fps)


def frame_size(width: int, height: int) -> tuple[float, float]:
    """Scene frame size in Manim units for a pixel resolution.

    Landscape keeps Manim's standard 8-unit height. Portrait keeps the frame
    8 units wide, so content that fits a landscape frame's height still fits
    across, and extends the height to match.
    """
    if width >= height:
        return 8.0 * width / height, 8.0
    return 8.0, 8.0 * height / width


@dataclass
class RenderJob:
    script: str
    scene: str  # a scene class name, or ALL_SCENES
    width: int
    height: int
    fps: int
    output_dir: Path
    workspace: Path

    @property
    def video_dir(self) -> Path:
        orientation = "portrait" if self.height > self.width else "landscape"
        return self.output_dir / f"{min(self.width, self.height)}p{self.fps}-{orientation}"

    @property
    def script_path(self) -> Path:
        return self.workspace / "scripts" / SCRIPT_NAME

    @property
    def config_path(self) -> Path:
        return self.workspace / "scripts" / "render.cfg"


def write_render_config(job: RenderJob) -> None:
    """Write a Manim config file for the job.

    Manim's -r flag changes the pixel size but not the scene frame, so a
    portrait render would be squashed; setting both here avoids that. Any
    manim.cfg the user keeps in the workspace (e.g. a background colour) is
    used as the base.
    """
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(job.workspace / "manim.cfg", encoding="utf-8")
    if not cfg.has_section("CLI"):
        cfg.add_section("CLI")

    frame_w, frame_h = frame_size(job.width, job.height)
    cache = job.workspace / "cache"
    cfg["CLI"].update(
        media_dir=cache.as_posix(),
        video_dir=job.video_dir.as_posix(),
        partial_movie_dir=(cache / "partial_movie_files" / "{scene_name}").as_posix(),
        images_dir=(job.output_dir / "images").as_posix(),
        pixel_width=str(job.width),
        pixel_height=str(job.height),
        frame_rate=str(job.fps),
        frame_width=str(frame_w),
        frame_height=str(frame_h),
    )
    with job.config_path.open("w", encoding="utf-8") as f:
        cfg.write(f)


def python_executable() -> str:
    """The interpreter to run Manim with: python.exe even if we're under pythonw.exe."""
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").exists():
        python = python.with_name("python.exe")
    return str(python)


def prepare_render(job: RenderJob) -> list[str]:
    """Write the script and config to the workspace and return the Manim command."""
    job.script_path.parent.mkdir(parents=True, exist_ok=True)
    job.script_path.write_text(job.script, encoding="utf-8")
    write_render_config(job)
    cmd = [
        python_executable(), "-m", "manim", "render",
        "--config_file", str(job.config_path),
        "--progress_bar", "none",
        str(job.script_path),
    ]
    cmd += ["-a"] if job.scene == ALL_SCENES else [job.scene]
    return cmd


def start_render(cmd: list[str], cwd: Path) -> subprocess.Popen:
    # A very wide COLUMNS stops Manim's rich logger wrapping each message
    # across several lines, so clean_log_line() sees whole records.
    env = dict(os.environ, PYTHONWARNINGS="ignore", COLUMNS="1000", PYTHONIOENCODING="utf-8")
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


_TIMESTAMP = re.compile(r"^\[\d\d/\d\d/\d\d \d\d:\d\d:\d\d\]\s*")
_SOURCE_SUFFIX = re.compile(r"\s+[\w.]+\.py:\d+\s*$")
_LEVEL = re.compile(r"^(INFO|DEBUG)\s+")
_PARTIAL = re.compile(r"^(Animation \d+) : Partial movie file written.*")
_CACHED = re.compile(r"^(Animation \d+) : Using cached data.*")
_BOX_CHARS = "│╭╰|+"


def clean_log_line(line: str) -> str | None:
    """Make one line of Manim's log readable in a narrow panel.

    Returns None for lines that only add noise (blank lines, bare level
    markers, temporary-file paths). Traceback boxes are left untouched.
    """
    line = line.rstrip()
    if line.lstrip()[:1] in _BOX_CHARS and line.strip():
        return line
    line = _SOURCE_SUFFIX.sub("", _TIMESTAMP.sub("", line)).strip()
    line = _LEVEL.sub("", line)
    if (
        not line
        or line in ("INFO", "DEBUG")
        or line.startswith(("File ready at", "Reading config file"))
    ):
        return None
    if line.startswith("Writing ") and "dvisvgm" in line:
        return "Compiling LaTeX…"
    line = _PARTIAL.sub(r"\1 rendered", line)
    line = _CACHED.sub(r"\1 (cached)", line)
    return re.sub(r"\s{2,}", "  ", line)


def error_summary(output: str) -> str | None:
    """Pull 'Line N of your script: SomeError: message' out of a failed render's output."""
    errors = re.findall(r"^\s*(\w+(?:Error|Exception)\b.*)$", output, re.MULTILINE)
    if not errors:
        return None
    lines = re.findall(re.escape(SCRIPT_NAME) + r":(\d+) in ", output)
    where = f"Line {lines[-1]} of your script: " if lines else ""
    return where + errors[-1].strip()


def new_videos(video_dir: Path, since: float) -> list[Path]:
    """Videos in video_dir written at or after `since` (a time.time() value), oldest first."""
    if not video_dir.is_dir():
        return []
    videos = [p for p in video_dir.glob("*.mp4") if p.stat().st_mtime >= since - 1]
    return sorted(videos, key=lambda p: p.stat().st_mtime)


def manim_installed() -> bool:
    return importlib.util.find_spec("manim") is not None


def latex_installed() -> bool:
    return shutil.which("latex") is not None


def open_path(path: Path) -> None:
    """Open a file or folder with the system's default application."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
