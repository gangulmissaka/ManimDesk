# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
import sys
from pathlib import Path

import pytest

from manimdesk import environment as envmod
from manimdesk.environment import (
    Environment,
    InstallError,
    Installer,
    active_environment,
    default_video_dir,
    find_tex_bin,
    is_tex_safe,
    load_settings,
    save_settings,
    subprocess_env,
    tinytex_asset,
    venv_python,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MANIMDESK_CONFIG_DIR", str(tmp_path / "config"))


def make_env(root: Path, latex: bool = True) -> Path:
    python = venv_python(root / "venv")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    if latex:
        tex_bin = root / "tinytex" / "TinyTeX" / "bin" / "windows"
        tex_bin.mkdir(parents=True)
        (tex_bin / "latex.exe").write_bytes(b"")
    return root


def test_settings_round_trip():
    assert load_settings() == {}
    save_settings({"env_dir": "/somewhere"})
    assert load_settings() == {"env_dir": "/somewhere"}


def test_environment_from_root(tmp_path):
    root = make_env(tmp_path / "env")
    env = Environment.from_root(root)
    assert env.python == venv_python(root / "venv")
    assert env.tex_bin == root / "tinytex" / "TinyTeX" / "bin" / "windows"
    assert env.path_dirs() == [str(env.tex_bin)]
    assert env.has_latex()


def test_environment_without_latex(tmp_path):
    env = Environment.from_root(make_env(tmp_path / "env", latex=False))
    assert env.tex_bin is None
    assert env.path_dirs() == []


def test_environment_missing(tmp_path):
    assert Environment.from_root(tmp_path / "nothing") is None


def test_find_tex_bin_hidden_linux_folder(tmp_path):
    tex_bin = tmp_path / ".TinyTeX" / "bin" / "x86_64-linux"
    tex_bin.mkdir(parents=True)
    (tex_bin / "latex").write_bytes(b"")
    assert find_tex_bin(tmp_path) == tex_bin


def test_active_environment_prefers_installed(tmp_path, monkeypatch):
    root = make_env(tmp_path / "env")
    save_settings({"env_dir": str(root)})
    assert active_environment().root == root


def test_active_environment_falls_back(tmp_path, monkeypatch):
    save_settings({"env_dir": str(tmp_path / "deleted")})
    monkeypatch.setattr(envmod.importlib.util, "find_spec", lambda name: None)
    assert active_environment() is None
    monkeypatch.setattr(envmod.importlib.util, "find_spec", lambda name: object())
    env = active_environment()
    assert env.root is None and env.python.exists()


def test_tinytex_asset():
    assert tinytex_asset("win32", "AMD64") == "TinyTeX-1-windows.exe"
    assert tinytex_asset("darwin", "arm64") == "TinyTeX-1-darwin.tar.xz"
    assert tinytex_asset("linux", "x86_64", musl=False) == "TinyTeX-1-linux-x86_64.tar.xz"
    assert tinytex_asset("linux", "x86_64", musl=True) == "TinyTeX-1-linuxmusl-x86_64.tar.xz"
    assert tinytex_asset("linux", "aarch64", musl=False) == "TinyTeX-1-linux-arm64.tar.xz"
    with pytest.raises(InstallError):
        tinytex_asset("linux", "riscv64", musl=False)


def test_is_tex_safe():
    assert is_tex_safe(Path("/home/sam/ManimDesk"))
    assert not is_tex_safe(Path("/Users/Sam Smith/ManimDesk"))
    assert not is_tex_safe(Path("/home/zoë/ManimDesk"))


def test_default_video_dir():
    path = default_video_dir()
    assert path.name == "ManimDesk"
    assert path.is_absolute()


def test_subprocess_env_prepends_path():
    env = subprocess_env(["/tex/bin"], FOO="1")
    assert env["PATH"].split(__import__("os").pathsep)[0] == "/tex/bin"
    assert env["FOO"] == "1"


def test_installer_steps(tmp_path):
    with_latex = Installer(tmp_path, True, log=print, progress=lambda f, l: None)
    without = Installer(tmp_path, False, log=print, progress=lambda f, l: None)
    assert len(with_latex.steps()) == len(without.steps()) + 3
    assert with_latex.steps()[-1][0] == without.steps()[-1][0] == "Checking that everything works"


def test_installer_reports_failure(tmp_path):
    installer = Installer(tmp_path, False, log=lambda text: None, progress=lambda f, l: None)
    with pytest.raises(InstallError):
        installer._run([sys.executable, "-c", "raise SystemExit(3)"])
