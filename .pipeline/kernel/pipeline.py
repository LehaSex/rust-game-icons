
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
INPUT = Path(os.environ.get("DELTA_INPUT", "/kaggle/input/rust-icons-delta"))
OUT = Path(os.environ.get("DELTA_OUT", "/kaggle/working"))

# Best fidelity to the original Rust asset on large/, measured as PSNR/SSIM
# against the true 1080 source, averaged over 128/180/256 px inputs:
# 26.55 dB / 0.7993, against 25.48 / 0.7811 for plain Lanczos.
# On Kaggle the weights sit next to this file; in the repository one level up.
MODEL = Path(os.environ.get("UPSCALER_MODEL")
             or (HERE / "models" / "RealESRGAN_x4plus.pth"))
if not MODEL.is_file():
    MODEL = HERE.parent / "models" / "RealESRGAN_x4plus.pth"

LARGE_SIZE = 1080
SMALL_SIZE = 180
WEBP_QUALITY = 90

REQUIRED_CATEGORIES = {
    "ammo", "attire", "components", "construction", "electrical", "food",
    "fun", "items", "medical", "misc", "resources", "tools", "traps", "weapons",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_needed() -> list[dict]:
    path = INPUT / "needed.json"
    if not path.is_file():
        log("no needed.json — nothing to do")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("items", data if isinstance(data, list) else [])


def upscale_batch(src_dir: Path, stage_dir: Path, names: list[str]) -> set[str]:
    in_dir = stage_dir / "in"
    out_dir = stage_dir / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in names:
        src = src_dir / f"{name}.png"
        if not src.is_file():
            log(f"  ! no source for {name}.png")
            continue
        (in_dir / f"{name}.png").write_bytes(src.read_bytes())

    if not any(in_dir.glob("*.png")):
        return set()

    cmd = [
        sys.executable, str(HERE / "tile_upscale.py"),
        "--in-dir", str(in_dir), "--out-dir", str(out_dir), "--model", str(MODEL),
    ]
    log(f"upscaling {len(list(in_dir.glob('*.png')))} icons...")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.stdout:
        for line in proc.stdout.strip().splitlines()[-5:]:
            log(f"  {line}")
    if proc.returncode != 0:
        log(f"! tile_upscale failed ({proc.returncode}): {proc.stderr[-400:]}")

    return {p.stem for p in out_dir.glob("*.png")}


def finalize(small_name: str, large_src: Path | None, item: dict) -> bool:
    name = item["shortname"]
    cat = item.get("category") or "items"
    small_src = INPUT / "src" / f"{name}.png"
    if not small_src.is_file():
        return False

    for sub in ("large", "small", "webp"):
        (OUT / "icons" / sub / cat).mkdir(parents=True, exist_ok=True)

    with Image.open(small_src) as img:
        src = img.convert("RGBA")
        src.load()
    src.save(OUT / "icons" / "small" / cat / f"{name}.png", optimize=True)
    src.save(OUT / "icons" / "webp" / cat / f"{name}.webp",
             "WEBP", quality=WEBP_QUALITY, method=4)

    if large_src is not None and large_src.is_file():
        shutil_copy(large_src, OUT / "icons" / "large" / cat / f"{name}.png")
    else:
                                                                                
                                                                
        src.save(OUT / "icons" / "large" / cat / f"{name}.png", optimize=True)
    return True


def shutil_copy(src: Path, dst: Path) -> None:
    dst.write_bytes(src.read_bytes())


MANIFEST = OUT / "manifest.json"


def write_manifest(manifest: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    needed = load_needed()
    if not needed:
        log("empty delta — skipping the run")
        write_manifest({"items": [], "count": 0})
        return 0

    log(f"delta: {len(needed)} items")
    names = [i["shortname"] for i in needed if i.get("shortname")]

    stage = Path("/kaggle/working/stage")
    done_names = upscale_batch(INPUT / "src", stage, names)
    log(f"upscale succeeded for {len(done_names)} of {len(names)}")

    written: list[str] = []
    for item in needed:
        name = item["shortname"]
        large = stage / "out" / f"{name}.png" if name in done_names else None
        try:
            if finalize(name, large, item):
                written.append(name)
        except Exception as exc:
            log(f"  ! {name}: {exc}")

    manifest = {
        "count": len(written),
        "requested": len(names),
        "upscaled": len(done_names),
        "items": sorted(written),
    }
    write_manifest(manifest)
    log(f"wrote {len(written)} icons to {OUT / 'icons'}")

    unknown = {i.get("category") for i in needed} - REQUIRED_CATEGORIES - {None}
    if unknown:
        log(f"! unknown categories: {sorted(unknown)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())