
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".pipeline"))
from paths import resolve_items_dir
from sync_icons import CATEGORY_MAP, DEFAULT_CATEGORY, norm_shortname


PIPELINE = Path(__file__).resolve().parents[2] / ".pipeline"


def repo_shortnames(repo_dir: Path) -> set[str]:
    path = repo_dir / "items.json"
    if not path.is_file():
        sys.exit(f"no items.json in {repo_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])
    return {i["image_name"] for i in items if i.get("image_name")}


def game_items(items_path: Path) -> tuple[dict[str, dict], list[dict]]:
    """Game items keyed by their dotted shortname, plus the aliases seen.

    The game ships aliases: `2module car.json` sits next to `2module.car.json`,
    and items like `legacy bow` exist only with a space while the repository
    stores `legacy.bow`. Comparing anything else makes every alias look like a
    brand new item, so the delta fills with duplicates that already have icons.
    """
    raw: list[dict] = []
    for jf in items_path.glob("*.json"):
        try:
            d = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        game_name = str(d.get("shortname") or "").strip()
        if not game_name:
            continue
        raw.append({
            "shortname": game_name,
            "itemid": d.get("itemid"),
            "name": d.get("Name"),
            "category": d.get("Category"),
        })

    found: dict[str, dict] = {}
    for entry in raw:
        key = norm_shortname(entry["shortname"])
        seen = found.get(key)
        if seen is None or (" " in seen["shortname"] and " " not in entry["shortname"]):
            found[key] = entry

    notes: list[dict] = []
    for entry in raw:
        key = norm_shortname(entry["shortname"])
        if found[key] is entry:
            kind = "renamed" if entry["shortname"] != key else "ok"
        else:
            kind = "collapsed"
        if kind != "ok":
            notes.append({"kind": kind, "game": entry["shortname"], "key": key,
                          "itemid": entry["itemid"]})
    return found, notes


def report_aliases(notes: list[dict], known: set[str], summary: Path | None) -> None:
    if not notes:
        print("  alias normalisation: nothing to rename")
        return

    print(f"  alias normalisation ({len(notes)}):")
    for note in sorted(notes, key=lambda n: (n["kind"], n["key"])):
        mark = "known" if note["key"] in known else "NEW"
        print(f"    [{mark:5}] {note['kind']:9} {note['game']:28} -> {note['key']:28} id {note['itemid']}")

    if summary is None:
        return
    with summary.open("a", encoding="utf-8") as fh:
        fh.write("### Alias normalisation\n\n")
        fh.write("| game shortname | repository shortname | itemid | status |\n")
        fh.write("|---|---|---|---|\n")
        for note in sorted(notes, key=lambda n: (n["kind"], n["key"])):
            mark = "known" if note["key"] in known else "**new**"
            fh.write(f"| `{note['game']}` | `{note['key']}` | {note['itemid']} | {mark} |\n")
        fh.write("\n")


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
    """Game spellings ("Weapon", "Ammunition") to the folders this repo uses.

    The kernel writes icons into `<category>/` and items.json records the same
    value, so both sides have to agree with sync_icons.CATEGORY_MAP — a raw
    lowercase of "Weapon" would create a second `weapon/` folder next to
    `weapons/` and fail schema validation.
    """
    raw = (cat or "").strip()
    mapped = CATEGORY_MAP.get(raw, DEFAULT_CATEGORY)
    if raw and raw not in CATEGORY_MAP:
        print(f"  ! unknown category {raw!r} -> {DEFAULT_CATEGORY}")
    return mapped


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

    have = {norm_shortname(n) for n in repo_shortnames(repo_dir)}
    game, alias_notes = game_items(src_dir)
    missing = {s: m for s, m in game.items() if s not in have}

    out = args.out
    src_out = out / "src"
    if src_out.exists():
        shutil.rmtree(src_out)
    src_out.mkdir(parents=True, exist_ok=True)

    payload: list[dict] = []
    copied = 0
    for shortname, meta in sorted(missing.items()):
        game_name = meta.get("shortname") or shortname
        png = next((p for p in (src_dir / f"{game_name}.png", src_dir / f"{shortname}.png")
                    if p.is_file()), None)
        if args.include_png:
            if png is None:
                print(f"  ! no PNG for {game_name}, skipping")
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
    report_aliases(alias_notes, have, summary_path())
    print(f"in game {len(game)}, in repo {len(have)}, delta {len(payload)} (PNGs copied {copied})")
    print(f"needed.json sha256[:12] = {digest}")
    print(f"has_delta={'true' if payload else 'false'}")
    set_outputs(payload)
    if not payload:
        print("no delta — no reason to go to Kaggle")
    return 0


def summary_path() -> Path | None:
    raw = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    return Path(raw) if raw else None


def set_outputs(payload: list[dict]) -> None:
    raw = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not raw:
        return
    with Path(raw).open("a", encoding="utf-8") as fh:
        fh.write(f"has_delta={'true' if payload else 'false'}\n")
        fh.write(f"delta_count={len(payload)}\n")


if __name__ == "__main__":
    sys.exit(main())