# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
"""Where ManimDesk keeps Python, Manim and LaTeX, and how it installs them.

An installed environment is one folder the user picks:

    <root>/
    ├── python/     private Python, downloaded by uv
    ├── venv/       Manim and the maths/science packages
    ├── tinytex/    portable LaTeX (TinyTeX)
    ├── scripts/    the last script rendered
    ├── cache/      Manim's temporary files
    └── manimdesk-env.json
"""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PYTHON_VERSION = "3.13"
PYTHON_PACKAGES = ["manim", "numpy", "scipy", "sympy", "matplotlib"]
# LaTeX packages Manim's templates and common examples use (TinyTeX-1 has the basics).
TEX_PACKAGES = [
    "standalone", "preview", "dvisvgm", "babel-english", "amsmath", "amsfonts",
    "doublestroke", "setspace", "rsfs", "relsize", "ragged2e", "fundus-calligra",
    "microtype", "wasy", "wasysym", "physics", "jknapltx", "mathastext",
    "cbfonts-fd", "everysel", "xcolor",
]
# Files Manim's default LaTeX template can't work without.
TEX_CHECK_FILES = ["standalone.cls", "preview.sty", "english.ldf", "amsmath.sty"]
TINYTEX_URL = "https://github.com/rstudio/tinytex-releases/releases/download/daily/{}"
CTAN_REPOSITORY = "https://mirror.ctan.org/systems/texlive/tlnet"
TINYTEX_REPOSITORY = "https://tlnet.yihui.org"
# Packages that include programs, published per platform (e.g. dvisvgm.windows.tar.xz).
TEX_BINARY_PACKAGES = ["dvisvgm"]
MARKER = "manimdesk-env.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------- locations ----------

def config_dir() -> Path:
    """Where settings.json lives. Override with MANIMDESK_CONFIG_DIR."""
    if os.environ.get("MANIMDESK_CONFIG_DIR"):
        return Path(os.environ["MANIMDESK_CONFIG_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "ManimDesk"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ManimDesk"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "manimdesk"


def load_settings() -> dict:
    try:
        return json.loads((config_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def is_tex_safe(path: Path) -> bool:
    """TeX tools can break on paths with spaces or non-ASCII characters."""
    text = str(path)
    return text.isascii() and " " not in text


def default_install_dir() -> Path:
    path = Path.home() / "ManimDesk"
    if sys.platform == "win32" and not is_tex_safe(path):
        path = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ManimDesk"
    return path


def default_workspace() -> Path:
    """Scripts and cache when no environment is installed. Override with MANIMDESK_HOME."""
    return Path(os.environ.get("MANIMDESK_HOME") or Path.home() / "ManimDesk")


def default_video_dir() -> Path:
    """The user's Videos folder (Movies on macOS), plus ManimDesk."""
    return _videos_folder() / "ManimDesk"


def _videos_folder() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes

            # FOLDERID_Videos; follows the folder if the user moved it (e.g. to OneDrive).
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(
                uuid.UUID("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}").bytes_le
            )
            path = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(path)
            ) == 0:
                try:
                    return Path(path.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(path)
        except (AttributeError, OSError):
            pass
        return Path.home() / "Videos"
    if sys.platform == "darwin":
        return Path.home() / "Movies"
    try:
        out = subprocess.run(
            ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if out and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Videos"


# ---------- environments ----------

def venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def find_tex_bin(tex_root: Path) -> Path | None:
    """The TinyTeX bin/<platform> folder under tex_root, if LaTeX is there."""
    for folder in sorted(tex_root.glob("*/bin/*")):
        if (folder / "latex").exists() or (folder / "latex.exe").exists():
            return folder
    return None


def python_executable() -> str:
    """This interpreter: python.exe even if we're running under pythonw.exe."""
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").exists():
        python = python.with_name("python.exe")
    return str(python)


@dataclass
class Environment:
    python: Path
    root: Path | None = None  # None: the Python ManimDesk itself runs on
    tex_bin: Path | None = None

    @classmethod
    def from_root(cls, root: Path) -> Environment | None:
        python = venv_python(root / "venv")
        if not python.exists():
            return None
        return cls(python=python, root=root, tex_bin=find_tex_bin(root / "tinytex"))

    def path_dirs(self) -> list[str]:
        """Folders to put in front of PATH when running Manim."""
        return [str(self.tex_bin)] if self.tex_bin else []

    def has_latex(self) -> bool:
        return self.tex_bin is not None or shutil.which("latex") is not None


def active_environment() -> Environment | None:
    """The installed environment, else this Python if it has Manim, else None."""
    root = load_settings().get("env_dir")
    if root:
        env = Environment.from_root(Path(root))
        if env:
            return env
    if importlib.util.find_spec("manim") is not None:
        return Environment(python=Path(python_executable()))
    return None


def subprocess_env(extra_path=(), **extra: str) -> dict:
    env = dict(os.environ, **extra)
    if extra_path:
        env["PATH"] = os.pathsep.join([*extra_path, env.get("PATH", "")])
    return env


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a process and anything it started (tlmgr.bat starts Perl, for example)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            creationflags=NO_WINDOW,
        )
    else:
        proc.terminate()


# ---------- platform checks ----------

def tinytex_asset(system: str = sys.platform, machine: str | None = None, musl: bool | None = None) -> str:
    """File name of the TinyTeX bundle for this computer."""
    machine = (machine or platform.machine()).lower()
    if system == "win32":
        return "TinyTeX-1-windows.exe"
    if system == "darwin":
        return "TinyTeX-1-darwin.tar.xz"
    if system.startswith("linux"):
        if musl is None:
            musl = any(Path("/lib").glob("ld-musl-*"))
        if machine in ("x86_64", "amd64"):
            return "TinyTeX-1-linuxmusl-x86_64.tar.xz" if musl else "TinyTeX-1-linux-x86_64.tar.xz"
        if machine in ("aarch64", "arm64") and not musl:
            return "TinyTeX-1-linux-arm64.tar.xz"
    raise InstallError(f"There's no ready-made LaTeX for {system} ({machine}).")


def build_tools_command() -> str | None:
    """On macOS/Linux, a command that installs what Manim needs to compile, if anything is missing.

    Windows has ready-made packages for everything, so it never needs this.
    """
    if sys.platform == "win32" or _have_build_tools():
        return None
    if sys.platform == "darwin":
        return "brew install pkg-config cairo pango"
    ids = _linux_ids()
    if ids & {"debian", "ubuntu"}:
        return "sudo apt install build-essential pkg-config libcairo2-dev libpango1.0-dev"
    if ids & {"fedora", "rhel", "centos"}:
        return "sudo dnf install gcc pkgconf-pkg-config cairo-devel pango-devel perl"
    if ids & {"arch"}:
        return "sudo pacman -S --needed base-devel pkgconf cairo pango perl"
    if ids & {"suse", "opensuse"}:
        return "sudo zypper install gcc pkg-config cairo-devel pango-devel perl"
    return "Install a C compiler, pkg-config, Perl and the Cairo and Pango development packages."


def _have_build_tools() -> bool:
    if not shutil.which("pkg-config"):
        return False
    libs = subprocess.run(["pkg-config", "--exists", "cairo", "pangocairo"], capture_output=True)
    if libs.returncode != 0:
        return False
    return sys.platform == "darwin" or bool(shutil.which("cc") or shutil.which("gcc"))


def _linux_ids() -> set[str]:
    try:
        info = platform.freedesktop_os_release()
    except OSError:
        return set()
    return {info.get("ID", ""), *info.get("ID_LIKE", "").split()}


def uv_bin() -> str:
    try:
        from uv import find_uv_bin

        return find_uv_bin()
    except (ImportError, FileNotFoundError):
        found = shutil.which("uv")
        if found:
            return found
    raise InstallError("The 'uv' tool wasn't found. Reinstall ManimDesk, or run: pip install uv")


# ---------- installing ----------

class InstallError(Exception):
    pass


class InstallCancelled(Exception):
    pass


CHECK_SCENE = '''from manim import *


class InstallCheck(Scene):
    def construct(self):
        self.add({mobject})
'''


class Installer:
    """Installs everything into `root`. Call run() on a worker thread.

    `log` receives output text; `progress` receives (fraction 0..1, step label).
    Steps that are already done are skipped, so running it again repairs an install.
    """

    def __init__(
        self,
        root: Path,
        with_latex: bool,
        log: Callable[[str], None],
        progress: Callable[[float, str], None],
    ):
        self.root = root
        self.with_latex = with_latex
        self.log = log
        self.progress = progress
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._span = (0.0, 0.0, "")
        self.venv_python = venv_python(root / "venv")
        self.tex_dir = root / "tinytex"
        self.uv_env = subprocess_env(
            UV_PYTHON_INSTALL_DIR=str(root / "python"),
            UV_PYTHON_PREFERENCE="only-managed",
            UV_NO_PROGRESS="1",
            NO_COLOR="1",
        )

    def steps(self) -> list[tuple[str, int, Callable[[], None]]]:
        steps = [
            (f"Downloading Python {PYTHON_VERSION}", 10, self.install_python),
            ("Creating the Python environment", 3, self.create_venv),
            ("Installing Manim, NumPy, SciPy, SymPy and Matplotlib", 40, self.install_packages),
        ]
        if self.with_latex:
            steps += [
                ("Downloading LaTeX (TinyTeX)", 20, self.download_tinytex),
                ("Unpacking LaTeX", 7, self.unpack_tinytex),
                ("Installing LaTeX packages for Manim", 15, self.install_tex_packages),
            ]
        steps.append(("Checking that everything works", 5, self.verify))
        return steps

    def cancel(self) -> None:
        self._cancel.set()
        if self._proc:
            kill_tree(self._proc)

    def run(self) -> Environment:
        steps = self.steps()
        total = sum(weight for _, weight, _ in steps)
        done = 0
        self.root.mkdir(parents=True, exist_ok=True)
        for label, weight, step in steps:
            self._check_cancel()
            self._span = (done / total, weight / total, label)
            self.progress(done / total, label)
            self.log(f"\n▸ {label}\n")
            step()
            done += weight
        self.progress(1.0, "Done")

        (self.root / MARKER).write_text(
            json.dumps(
                {
                    "python": PYTHON_VERSION,
                    "packages": PYTHON_PACKAGES,
                    "latex": self.with_latex,
                    "installed": datetime.datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        save_settings({**load_settings(), "env_dir": str(self.root)})
        return Environment.from_root(self.root)

    # ----- steps -----

    def install_python(self):
        self._run([uv_bin(), "python", "install", PYTHON_VERSION], env=self.uv_env)

    def create_venv(self):
        if self.venv_python.exists():
            self.log("Already set up, keeping it.\n")
            return
        self._run(
            [uv_bin(), "venv", "--python", PYTHON_VERSION, str(self.root / "venv")],
            env=self.uv_env,
        )

    def install_packages(self):
        self._run(
            [uv_bin(), "pip", "install", "--python", str(self.venv_python), *PYTHON_PACKAGES],
            env=self.uv_env,
        )

    def download_tinytex(self):
        if find_tex_bin(self.tex_dir):
            self.log("LaTeX is already here, skipping the download.\n")
            return
        asset = tinytex_asset()
        url = TINYTEX_URL.format(asset)
        target = self.tex_dir / asset
        self.tex_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"{url}\n")
        try:
            self._download(url, target)
        except (ssl.SSLError, urllib.error.URLError) as e:
            # Some Python builds (e.g. python.org on macOS) lack root certificates.
            if not shutil.which("curl"):
                raise InstallError(f"Download failed: {e}") from e
            self.log(f"Python couldn't download it ({e}); trying curl…\n")
            self._run(["curl", "-fL", "--retry", "3", "-o", str(target), url])

    def unpack_tinytex(self):
        if find_tex_bin(self.tex_dir):
            self.log("Already unpacked.\n")
            return
        archive = self.tex_dir / tinytex_asset()
        if archive.suffix == ".exe":
            # Self-extracting archive: unpacks a TinyTeX folder into the current folder.
            self._run([str(archive), "-y"], cwd=self.tex_dir)
        else:
            with tarfile.open(archive) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(self.tex_dir, filter="data")
                else:
                    tar.extractall(self.tex_dir)
        archive.unlink(missing_ok=True)
        if not find_tex_bin(self.tex_dir):
            raise InstallError("LaTeX was unpacked, but its programs weren't found.")

    def install_tex_packages(self):
        tex_bin = find_tex_bin(self.tex_dir)
        if not self._missing_tex_files(tex_bin):
            self.log("LaTeX packages are already installed.\n")
            return
        # TeX Live's own package manager often fails to download (old tlmgr versions,
        # certificate checks, proxies), so fetch the package archives directly first.
        self._download_tex_packages(tex_bin)
        if not self._missing_tex_files(tex_bin):
            return
        self.log("\nSome packages are still missing; trying TeX Live's package manager…\n")
        self._tlmgr_install(tex_bin)

    def _download_tex_packages(self, tex_bin: Path):
        """Unpack each package's archive from a TeX Live repository into TinyTeX."""
        tex_root = tex_bin.parent.parent
        names = [f"{name}.tar.xz" for name in TEX_PACKAGES]
        names += [f"{name}.{tex_bin.name}.tar.xz" for name in TEX_BINARY_PACKAGES]
        failed = []
        for i, name in enumerate(names):
            self._check_cancel()
            self._sub_progress(i / len(names))
            for repo in (CTAN_REPOSITORY, TINYTEX_REPOSITORY):
                try:
                    request = urllib.request.Request(
                        f"{repo}/archive/{name}", headers={"User-Agent": "ManimDesk"}
                    )
                    with urllib.request.urlopen(request, timeout=60) as response:
                        data = response.read()
                    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
                        # Most packages are "relocatable": their paths (tex/latex/...)
                        # belong inside texmf-dist. Programs come as bin/<platform>/...
                        tops = {m.name.split("/", 1)[0] for m in tar.getmembers()}
                        dest = tex_root if tops & {"bin", "texmf-dist"} else tex_root / "texmf-dist"
                        if hasattr(tarfile, "data_filter"):
                            tar.extractall(dest, filter="data")
                        else:
                            tar.extractall(dest)
                    self.log(f"  {name}\n")
                    break
                except (OSError, urllib.error.URLError, tarfile.TarError) as e:
                    error = e
            else:
                failed.append(name)
                self.log(f"  {name}: couldn't download ({error})\n")
        if failed:
            self.log(f"{len(failed)} package(s) couldn't be downloaded.\n")
        # Rebuild LaTeX's file index so it finds the new files.
        mktexlsr = tex_bin / ("mktexlsr.exe" if sys.platform == "win32" else "mktexlsr")
        try:
            self._run([str(mktexlsr)])
        except InstallError as e:
            self.log(f"{e}\n")

    def _tlmgr_install(self, tex_bin: Path):
        tlmgr = str(tex_bin / ("tlmgr.bat" if sys.platform == "win32" else "tlmgr"))
        env = subprocess_env([str(tex_bin)])
        if sys.platform == "win32":
            # tlmgr prefers Windows' own curl, which fails on networks where certificate
            # revocation can't be checked; TeX Live's bundled wget doesn't do that check.
            env["TEXLIVE_DOWNLOADER"] = "wget"
        # tlmgr.bat exits with 0 even when it fails, so success is judged by
        # whether the packages are actually there afterwards.
        for attempt, repository in enumerate([None, CTAN_REPOSITORY], start=1):
            if attempt > 1:
                self.log(f"\nSome LaTeX packages are still missing; trying again ({attempt}/2)…\n")
            repo_args = ["--repository", repository] if repository else []
            try:
                # A TinyTeX build can be older than the package server, which then
                # refuses to install anything until tlmgr updates itself.
                self._run([tlmgr, *repo_args, "update", "--self"], env=env)
                self._run([tlmgr, *repo_args, "install", *TEX_PACKAGES], env=env)
            except InstallError as e:
                self.log(f"{e}\n")
            missing = self._missing_tex_files(tex_bin)
            if not missing:
                return
        raise InstallError(
            "Couldn't download the LaTeX packages Manim needs (missing: "
            + ", ".join(missing)
            + "). Check your internet connection and click Try again."
        )

    def _missing_tex_files(self, tex_bin: Path) -> list[str]:
        kpsewhich = tex_bin / ("kpsewhich.exe" if sys.platform == "win32" else "kpsewhich")
        missing = []
        for name in TEX_CHECK_FILES:
            found = subprocess.run(
                [str(kpsewhich), name], capture_output=True, text=True, creationflags=NO_WINDOW
            ).stdout.strip()
            if not found:
                missing.append(name)
        if not any((tex_bin / name).exists() for name in ("dvisvgm", "dvisvgm.exe")):
            missing.append("dvisvgm")
        return missing

    def verify(self):
        env = Environment.from_root(self.root)
        if env is None:
            raise InstallError("The Python environment is missing.")
        self._run(
            [str(env.python), "-c",
             "import sys, manim; print('Manim', manim.__version__, 'on Python', sys.version.split()[0])"],
            env=subprocess_env(PYTHONWARNINGS="ignore"),
        )
        if not env.has_latex():
            self.log("No LaTeX: text and maths that use Tex or MathTex won't render.\n")
        scripts = self.root / "scripts"
        scripts.mkdir(exist_ok=True)
        mobject = r'MathTex(r"\int_0^1 x\,dx = \tfrac{1}{2}")' if env.has_latex() else "Circle()"
        (scripts / "install_check.py").write_text(
            CHECK_SCENE.format(mobject=mobject), encoding="utf-8"
        )
        try:
            self._run(
                [str(env.python), "-m", "manim", "render", "-ql", "--dry_run",
                 "--progress_bar", "none", "--media_dir", str(self.root / "cache"),
                 "install_check.py", "InstallCheck"],
                cwd=scripts,
                env=subprocess_env(env.path_dirs(), PYTHONWARNINGS="ignore", COLUMNS="1000",
                                   PYTHONIOENCODING="utf-8"),
            )
        except InstallError:
            raise InstallError("Manim couldn't render a test scene; the log above shows why.") from None
        self.log("✔ Manim rendered a test scene" + (" with LaTeX.\n" if env.has_latex() else ".\n"))

    # ----- helpers -----

    def _check_cancel(self):
        if self._cancel.is_set():
            raise InstallCancelled()

    def _sub_progress(self, fraction: float):
        start, span, label = self._span
        self.progress(start + span * min(fraction, 1.0), label)

    def _run(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None):
        self._check_cancel()
        self._proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
        )
        for line in self._proc.stdout:
            self.log(line)
        code = self._proc.wait()
        self._proc = None
        self._check_cancel()
        if code != 0:
            raise InstallError(f"{Path(cmd[0]).name} {cmd[1]} failed (exit code {code}).")

    def _download(self, url: str, target: Path):
        part = target.with_name(target.name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "ManimDesk"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as f:
            size = int(response.headers.get("Content-Length") or 0)
            got = 0
            while chunk := response.read(1 << 20):
                self._check_cancel()
                f.write(chunk)
                got += len(chunk)
                if size:
                    self._sub_progress(got / size)
        self.log(f"Downloaded {got / 1e6:.0f} MB.\n")
        part.replace(target)
