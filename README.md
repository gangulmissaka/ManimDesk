# ManimDesk

A simple desktop app for turning [Manim](https://www.manim.community/) scripts into videos.
Paste a script, pick the quality and aspect ratio, and click **Render**. No command line needed.

Works on **Windows, macOS and Linux**.

![ManimDesk screenshot](docs/screenshot.png)

## Features

- **Script editor:** paste, open or save Manim scripts.
- **Scene picker:** finds every `Scene` class in your script automatically, with an option to render them all.
- **Quality:** 480p (15 fps), 720p (30 fps) or 1080p HD (60 fps).
- **Aspect ratio:** 16:9 landscape for YouTube, or 9:16 portrait for Shorts, Reels and TikTok.
- **Live render log** with errors highlighted, plus one-click buttons to open the video or its folder.

## Requirements

| Requirement | Notes |
|---|---|
| **Python 3.11+** | [python.org](https://www.python.org/downloads/) |
| **LaTeX** (optional, recommended) | Needed for `Tex`, `MathTex` and numbered axes. Windows: [MiKTeX](https://miktex.org/). macOS: [MacTeX](https://www.tug.org/mactex/). Linux: `sudo apt install texlive texlive-latex-extra dvisvgm` |
| **Tk** (Linux only) | `sudo apt install python3-tk` |

On Linux, Manim may also need Cairo and Pango. See the
[Manim installation guide](https://docs.manim.community/en/stable/installation.html).

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install git+https://github.com/gangulmissaka/ManimDesk
```

Or with pip:

```bash
pip install git+https://github.com/gangulmissaka/ManimDesk
```

Add the `[science]` extra if your scripts use SciPy, SymPy or Matplotlib:

```bash
uv tool install "manimdesk[science] @ git+https://github.com/gangulmissaka/ManimDesk"
```

## Run

```bash
manimdesk
```

or `python -m manimdesk`.

## Where things are saved

ManimDesk keeps its files in `~/ManimDesk` (set the `MANIMDESK_HOME` environment variable to change this):

```
~/ManimDesk/
├── output/                     # default "Save to" folder
│   ├── 1080p60-landscape/HelloManim.mp4
│   └── 720p30-portrait/HelloManim.mp4
├── cache/                      # Manim's temporary files (safe to delete)
├── scripts/                    # the last script you rendered
└── manim.cfg                   # optional: your own Manim settings
```

To change Manim's defaults, such as the background colour, create `~/ManimDesk/manim.cfg`:

```ini
[CLI]
background_color = #0f0f14
```

ManimDesk's own quality, aspect-ratio and folder settings always take priority.

## Portrait (9:16) videos

In portrait mode the scene is **8 units wide and about 14.2 units tall**, instead of Manim's usual
14.2 × 8. A scene designed for landscape will still fit across the screen, with extra room above and below.
`to_edge(UP)` and `to_edge(DOWN)` place things at the real top and bottom of the portrait frame.

## Examples

The [`examples/`](examples) folder has ready-to-render scenes. Open one with **Open…** in the app:

- `maths.py`: Pythagorean theorem, a sine wave changing frequency, a rotating 3D surface
- `physics.py`: projectile motion, a swinging pendulum

## Development

```bash
git clone https://github.com/gangulmissaka/ManimDesk
cd ManimDesk
uv sync          # creates .venv with ManimDesk, Manim and pytest
uv run manimdesk # run the app
uv run pytest    # run the tests
```

## License

Copyright 2026 gangulmissaka.

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE).

ManimDesk is an independent project and is not affiliated with the Manim Community. Manim is
installed as a separate dependency under its own MIT License.
