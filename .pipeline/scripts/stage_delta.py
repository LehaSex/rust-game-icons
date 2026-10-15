
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".pipeline"))
from paths import resolve_items_dir

PIPELINE = Path(__file__).resolve().parents[2] / ".pipeline"


def repo_shortnames(repo_dir: Path) -> set[str]:
    path = repo_dir / "items.json"
    if not path.is_file():
        sys.exit(f"no items.json in {repo_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])
    return {i["image_name"] for i in items if i.get("image_name")}


def game_items(items_path: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for jf in items_path.glob("*.json"):
        try:
            d = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        shortname = d.get("shortname")
        if shortname:
            found[shortname] = {
                "shortname": shortname,
                "itemid": d.get("itemid"),
                "name": d.get("Name"),
                "category": d.get("Category"),
            }
    return found


def package_kernel(out: Path, pipeline_dir: Path) -> int:
    """Copy the kernel code and the upscale model into the delta dataset.

    The notebook pulls these from /kaggle/input, so they must travel with the
    package; a kernel pushed without them dies on import.
    """
    kernel = pipeline_dir / "kernel"
    if not kernel.is_dir():
        sys.exit(f"kernel sources not found: {kernel}")

    copied = 0
    for name in ("pipeline.py", "tile_upscale.py"):
        src = kernel / name
        if src.is_file():
            shutil.copy2(src, out / name)
            copied += 1

    models = out / "models"
    models.mkdir(exist_ok=True)
    weights = sorted((pipeline_dir / "models").glob("*.pth"))
    for src in weights:
        shutil.copy2(src, models / src.name)
        copied += 1
    if not weights:
        print(f"  ! no *.pth in {pipeline_dir / 'models'}; the kernel will fall back to "
              "no upscaling and write 180px icons straight into large/")
    return copied


def norm_category(cat: str | None) -> str:
    if not cat:
        return "items"
    c = cat.strip().lower()
    return c.replace(" ", "_") if c.isascii() else "items"


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble the icon delta for Kaggle")
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--items-dir", default=None)
    ap.add_argument("--repo-dir", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("delta-pkg"))
    ap.add_argument("--dataset-slug", default="", help="owner/slug of the private dataset")
    ap.add_argument("--include-png", action="store_true", default=True,
                    help="copy the PNGs (default: yes)")
    ap.add_argument("--no-include-png", dest="include_png", action="store_false")
    ap.add_argument("--no-kernel", dest="kernel", action="store_false", default=True,
                    help="do not package the kernel code and upscale model")
    args = ap.parse_args()

    repo_dir = args.repo_dir.resolve()
    src_dir = resolve_items_dir(args.items_dir, args.game_dir)
    if not src_dir.is_dir():
        sys.exit(f"icon folder not found: {src_dir}")

    have = repo_shortnames(repo_dir)
    game = game_items(src_dir)
    missing = {s: m for s, m in game.items() if s not in have}

    out = args.out
    src_out = out / "src"
    if src_out.exists():
        shutil.rmtree(src_out)
    src_out.mkdir(parents=True, exist_ok=True)

    payload: list[dict] = []
    copied = 0
    for shortname, meta in sorted(missing.items()):
        png = src_dir / f"{shortname}.png"
        if args.include_png:
            if not png.is_file():
                print(f"  ! no PNG for {shortname}, skipping")
                continue
            shutil.copy2(png, src_out / f"{shortname}.png")
            copied += 1
        payload.append({
            "shortname": shortname,
            "itemid": meta.get("itemid"),
            "name": meta.get("name"),
            "category": norm_category(meta.get("category")),
        })

    if args.kernel:
        n = package_kernel(out, PIPELINE)
        print(f"kernel files packaged: {n}")

    (out / "needed.json").write_text(
        json.dumps({"generated": None, "count": len(payload), "items": payload},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.dataset_slug:
        owner, _, slug = args.dataset_slug.partition("/")
        (out / "dataset-metadata.json").write_text(
            json.dumps({
                "title": "Rust icons delta",
                "id": f"{owner}/{slug}",
                "licenses": [{"name": "other"}],
                "isPrivate": True,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    digest = hashlib.sha256(
        (out / "needed.json").read_bytes()
    ).hexdigest()[:12]
    print(f"in game {len(game)}, in repo {len(have)}, delta {len(payload)} (PNGs copied {copied})")
    print(f"needed.json sha256[:12] = {digest}")
    print(f"has_delta={'true' if payload else 'false'}")
    if not payload:
        print("no delta — no reason to go to Kaggle")
    return 0


if __name__ == "__main__":
    sys.exit(main())