from __future__ import annotations

import json
from pathlib import Path

MD = "markdown"


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}


def md_cell(text: str) -> dict:
    return {"cell_type": MD, "metadata": {}, "source": text}


def layout_source() -> str:
    return (
        "import os, shutil\n"
        "from pathlib import Path\n"
        "\n"
        "def find_delta(root='/kaggle/input'):\n"
        "    seen = set()\n"
        "    for base, dirs, files in os.walk(root, followlinks=True):\n"
        "        real = os.path.realpath(base)\n"
        "        if real in seen:\n"
        "            dirs[:] = []\n"
        "            continue\n"
        "        seen.add(real)\n"
        "        if 'needed.json' in files:\n"
        "            return Path(base)\n"
        "    raise SystemExit('needed.json not found under ' + root)\n"
        "\n"
        "DELTA = find_delta()\n"
        "WORK = Path('/kaggle/working/pipeline/kernel')\n"
        "(WORK / 'models').mkdir(parents=True, exist_ok=True)\n"
        "for item in DELTA.glob('*.py'):\n"
        "    shutil.copy2(item, WORK / item.name)\n"
        "for item in DELTA.glob('models/*.pth'):\n"
        "    shutil.copy2(item, WORK / 'models' / item.name)\n"
        "os.environ['DELTA_INPUT'] = str(DELTA)\n"
        "print('dataset:', DELTA)\n"
        "for path in sorted(WORK.rglob('*')):\n"
        "    print(' ', path.relative_to(WORK), path.stat().st_size)\n"
    )


def build_notebook(pipeline_py: Path, requirements: str, model_note: str = "") -> dict:
    install = (
        "from pathlib import Path\n"
        f"Path('/kaggle/working/requirements.txt').write_text({requirements!r}, encoding='utf-8')\n"
        "!pip install --quiet -r /kaggle/working/requirements.txt\n"
    )
    setup = (
        "import os, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, '/kaggle/working/pipeline/kernel')\n"
        f"HERE = Path('/kaggle/working/pipeline/kernel')\n"
        "os.environ.setdefault('UPSCALER_MODEL', str(HERE / 'models' / 'RealESRGAN_x4plus.pth'))\n"
        "print('delta input:', os.environ.get('DELTA_INPUT'))\n"
        "print('model:', os.environ['UPSCALER_MODEL'], os.path.exists(os.environ['UPSCALER_MODEL']))\n"
    )

    cells = [
        md_cell("## rust-icons-delta - upscale new icons\n\n"
                "Private kernel. Input is the delta dataset (needed.json + src/*.png), "
                "output is icons/ in /kaggle/working/out/."),
        md_cell("### deps"),
        code_cell(install),
        md_cell("### layout"),
        code_cell(layout_source()),
        md_cell("### setup"),
        code_cell(setup),
        md_cell("### run"),
        code_cell("runpy = __import__('runpy')\n"
                  "runpy.run_path(str(HERE / 'pipeline.py'), run_name='__main__')"),
    ]
    if model_note:
        cells.insert(3, md_cell(model_note))

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[2]
    pipeline_dir = root / ".pipeline"
    nb = build_notebook(pipeline_dir / "kernel" / "pipeline.py",
                        (pipeline_dir / "kernel" / "requirements-kernel.txt").read_text(encoding="utf-8"))
    out = root / "build" / "kernel" / "pipeline.ipynb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)