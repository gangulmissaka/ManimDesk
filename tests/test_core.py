# Copyright 2026 gangulmissaka
# SPDX-License-Identifier: Apache-2.0
import configparser
import sys

import pytest

from manimdesk.core import (
    ALL_SCENES,
    RenderJob,
    find_scenes,
    frame_size,
    new_videos,
    prepare_render,
    resolution,
)

SCRIPT = """
from manim import *
import manim

class A(Scene): pass
class B(ThreeDScene): pass
class C(manim.MovingCameraScene): pass
class Helper: pass
class D(VGroup): pass
"""


def test_find_scenes():
    assert find_scenes(SCRIPT) == ["A", "B", "C"]


def test_find_scenes_syntax_error():
    with pytest.raises(SyntaxError):
        find_scenes("class Broken(Scene)\n")


def test_resolution_orientation():
    assert resolution("1080p HD (60 fps)", portrait=False) == (1920, 1080, 60)
    assert resolution("1080p HD (60 fps)", portrait=True) == (1080, 1920, 60)


def test_frame_size_keeps_short_side_at_8_units():
    w, h = frame_size(1920, 1080)
    assert h == 8.0 and w == pytest.approx(14.222, abs=1e-3)
    w, h = frame_size(1080, 1920)
    assert w == 8.0 and h == pytest.approx(14.222, abs=1e-3)


def make_job(tmp_path, scene="A", width=720, height=1280, fps=30):
    return RenderJob(
        script=SCRIPT,
        scene=scene,
        width=width,
        height=height,
        fps=fps,
        output_dir=tmp_path / "out",
        workspace=tmp_path / "ws",
    )


def test_prepare_render_writes_files_and_command(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "manim.cfg").write_text("[CLI]\nbackground_color = #101010\n")
    job = make_job(tmp_path)
    cmd = prepare_render(job, "/env/python")

    assert job.script_path.read_text(encoding="utf-8") == SCRIPT
    assert cmd[:4] == ["/env/python", "-m", "manim", "render"]
    assert cmd[-2:] == [str(job.script_path), "A"]

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(job.config_path, encoding="utf-8")
    cli = cfg["CLI"]
    assert cli["background_color"] == "#101010"  # user setting kept
    assert (cli["pixel_width"], cli["pixel_height"], cli["frame_rate"]) == ("720", "1280", "30")
    assert float(cli["frame_width"]) == 8.0
    assert cli["video_dir"].endswith("out/720p30-portrait")
    assert cli["partial_movie_dir"].endswith("{scene_name}")


def test_prepare_render_all_scenes(tmp_path):
    cmd = prepare_render(make_job(tmp_path, scene=ALL_SCENES, width=1920, height=1080), "python")
    assert cmd[-1] == "-a"


def test_video_dir_names(tmp_path):
    assert make_job(tmp_path, width=1920, height=1080, fps=60).video_dir.name == "1080p60-landscape"
    assert make_job(tmp_path, width=480, height=854, fps=15).video_dir.name == "480p15-portrait"


def test_new_videos_filters_by_time(tmp_path):
    import os

    old = tmp_path / "old.mp4"
    new = tmp_path / "new.mp4"
    old.write_bytes(b"")
    new.write_bytes(b"")
    os.utime(old, (1000, 1000))
    assert new_videos(tmp_path, since=2000) == [new]
    assert new_videos(tmp_path / "missing", since=0) == []


def test_clean_log_line():
    from manimdesk.core import clean_log_line

    assert clean_log_line("Manim Community v0.22.1\n") == "Manim Community v0.22.1"
    assert clean_log_line("\n") is None
    assert clean_log_line(
        "[11/03/26 13:50:40] INFO     Animation 0 : Partial movie file written in 'C:/x/a.mp4'"
        "          scene_file_writer.py:173\n"
    ) == "Animation 0 rendered"
    assert clean_log_line("                    INFO     Rendered Ok          manager.py:226\n") == "Rendered Ok"
    assert clean_log_line("                    INFO                         scene_file_writer.py:999\n") is None
    assert clean_log_line("  File ready at 'C:/x/Ok.mp4'\n") is None
    assert clean_log_line("WARNING  Something odd    file.py:12\n") == "WARNING  Something odd"
    assert (
        clean_log_line("INFO  Animation 2 : Using cached data (hash : 8ae86_12_34)   cairo_renderer.py:9\n")
        == "Animation 2 (cached)"
    )
    assert clean_log_line("INFO  Reading config file: C:/ws/render.cfg   utils.py:1\n") is None
    assert (
        clean_log_line("INFO  Writing \\special{dvisvgm:raw <g>}Hi   tex_file_writing.py:9\n")
        == "Compiling LaTeX…"
    )
    box = "│ > 8 │     x = 1 / 0                                │"
    assert clean_log_line(box + "\n") == box


def test_error_summary():
    from manimdesk.core import SCRIPT_NAME, error_summary

    output = (
        f"│ C:/ws/scripts/{SCRIPT_NAME}:8 in construct          │\n"
        "│ ... except EndSceneEarlyException: │\n"
        "ZeroDivisionError: division by zero\n"
    )
    assert error_summary(output) == "Line 8 of your script: ZeroDivisionError: division by zero"
    assert error_summary("all good\n") is None


def test_pretty_path():
    from pathlib import Path

    from manimdesk.core import pretty_path

    assert pretty_path(Path.home() / "ManimDesk" / "output") == str(Path("~/ManimDesk/output"))
