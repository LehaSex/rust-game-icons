                      

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from paths import ENV_GAME_DIR, ENV_ITEMS_DIR, items_dir, resolve_items_dir, upscayl_bin, upscayl_models

                                                                             
              
                                                                             

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_DIR = SCRIPT_DIR.parent
DEFAULT_GAME_DIR = None

UPSCAYL_MODEL = os.environ.get("RUST_UPSCALER_MODEL", "upscayl-standard-4x")

LARGE_SIZE = 1080
SMALL_SIZE = 180
WEBP_QUALITY = 90
WEBP_METHOD = 4

                                                  
CATEGORY_MAP = {
    "Ammunition": "ammo",
    "Attire": "attire",
    "Component": "components",
    "Construction": "construction",
    "Electrical": "electrical",
    "Food": "food",
    "Fun": "fun",
    "Items": "items",
    "Medical": "medical",
    "Misc": "misc",
    "Resources": "resources",
    "Tool": "tools",
    "Traps": "traps",
    "Weapon": "weapons",
}
DEFAULT_CATEGORY = "items"

                                                        
CATEGORY_ORDER = [
    "ammo", "attire", "components", "construction", "electrical", "food",
    "fun", "items", "medical", "misc", "resources", "tools", "traps", "weapons",
]

                                                                             
         
                                                                             

report: dict[str, list] = {}


def prog(msg: str) -> None:
    print(msg, flush=True)


def log(section: str, line: str) -> None:
    report.setdefault(section, []).append(line)


def norm_shortname(s: str) -> str:
    return s.replace("%20", " ").replace(" ", ".").strip()


                                                                             
                      
                                                                             

def load_game_items(game_dir: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    jsons = sorted(game_dir.glob("*.json"))
    prog(f"    json files in game: {len(jsons)}")
    for n, jf in enumerate(jsons, 1):
        if n % 200 == 0:
            prog(f"    reading {n}/{len(jsons)}")
        try:
            data = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            log("game_json_errors", f"{jf.name}: {exc}")
            continue
        sn = str(data.get("shortname", "")).strip()
        itemid = data.get("itemid")
        if not sn or itemid is None:
            log("game_json_errors", f"{jf.name}: no shortname/itemid")
            continue
        key = norm_shortname(sn)
        png = jf.with_suffix(".png")
        if png.name != f"{sn}.png" and (game_dir / f"{sn}.png").exists():
            png = game_dir / f"{sn}.png"
        rep = entries.get(key)
        if rep is None:
            entries[key] = {
                "itemid": itemid,
                "shortname": sn,
                "name": str(data.get("Name", "")).strip(),
                "category": str(data.get("Category", "")).strip(),
                "png": png,
            }
            continue
        if rep["itemid"] != itemid:
            log(
                "itemid_conflicts",
                f"{key}: {rep['shortname']}={rep['itemid']} vs {sn}={itemid}",
            )
                                                                             
        if " " in rep["shortname"] and " " not in sn:
            rep["shortname"] = sn
            rep["name"] = str(data.get("Name", "")).strip()
            rep["png"] = png
    return entries


                                                                             
                  
                                                                             

def premultiply_rgba(img: Image.Image) -> Image.Image:
    arr = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    alpha = arr[..., 3:4]
    premul = (arr[..., :3] * alpha // 255).astype(np.uint8)
    out = np.concatenate([premul, np.full_like(premul[..., :1], 255)], axis=-1)
    return Image.fromarray(out, "RGBA")


def finalize_large(upscaled: Image.Image, src_alpha: Image.Image | None, size: int) -> Image.Image:
    rgb = np.asarray(
        upscaled.convert("RGB").resize((size, size), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    if src_alpha is None:
        a = np.full((size, size), 255, dtype=np.uint8)
    else:
        a = np.asarray(src_alpha.resize((size, size), Image.Resampling.LANCZOS), dtype=np.uint8)
    af = a.astype(np.float32)[..., None]
    rgb_out = np.where(af >= 8, np.clip(rgb * 255.0 / np.maximum(af, 8.0), 0, 255), 0).astype(np.uint8)
    return Image.fromarray(np.concatenate([rgb_out, a[..., None]], axis=-1), "RGBA")


def make_small(src: Image.Image, size: int) -> Image.Image:
    return src.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def upscale_batch_torch(pairs: list[tuple[Path, Path]], total_label: str) -> set[Path]:
    script = SCRIPT_DIR / "kernel" / "tile_upscale.py"
    if not script.is_file():
        prog(f"    ! not found {script}")
        return set()
    with tempfile.TemporaryDirectory(prefix="rust-icons-torch-") as td:
        in_dir = Path(td) / "in"
        out_dir = Path(td) / "out"
        in_dir.mkdir()
        out_dir.mkdir()
        for src_file, _ in pairs:
            shutil.copy2(src_file, in_dir / src_file.name)
        cmd = [sys.executable, str(script), "--in-dir", str(in_dir),
               "--out-dir", str(out_dir), "--model", str(torch_model())]
        if os.environ.get("RUST_UPSCALE_TILE"):
            cmd += ["--tile", os.environ["RUST_UPSCALE_TILE"]]
        prog(f"    Torch: {len(pairs)} icons ({total_label})...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                prog(f"      {line[:100]}")
        proc.wait()
        if proc.returncode != 0:
            prog(f"    ! tile_upscale.py exited with code {proc.returncode}")
        done: set[Path] = set()
        for _, dst in pairs:
            candidate = out_dir / dst.name
            if candidate.exists():
                shutil.copy2(candidate, dst)
                done.add(dst)
    prog(f"    Torch done: {len(done)}/{len(pairs)}")
    return done


def torch_model() -> Path:
    raw = os.environ.get("RUST_UPSCALER_MODEL_PATH", "").strip()
    if raw:
        return Path(raw)
    return SCRIPT_DIR / "models" / "RealESRGAN_x4plus.pth"


def upscale_batch(pairs: list[tuple[Path, Path]], total_label: str, backend: str = "upscayl") -> set[Path]:
    if not pairs:
        return set()
    if backend == "torch":
        return upscale_batch_torch(pairs, total_label)
    if backend == "none":
        prog(f"    Upscale disabled, {len(pairs)} icons ({total_label}) — Lanczos only")
        return set()
    bin_path = upscayl_bin()
    if bin_path is None:
        prog("    ! UPSCAYL_BIN not set, falling back to LANCZOS")
        return set()
    prog(f"    Upscayl: {len(pairs)} icons ({total_label}), model {UPSCAYL_MODEL}...")
    done: set[Path] = set()
    with tempfile.TemporaryDirectory(prefix="rust-icons-") as td:
        in_dir = Path(td) / "in"
        out_dir = Path(td) / "out"
        in_dir.mkdir()
        out_dir.mkdir()
        for src_file, _ in pairs:
            shutil.copy2(src_file, in_dir / src_file.name)
        cmd = [
            str(bin_path), "-i", str(in_dir), "-o", str(out_dir),
            "-m", str(upscayl_models()), "-n", UPSCAYL_MODEL, "-f", "png",
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line and not line.startswith("["):
                prog(f"      {line[:100]}")
        proc.wait()
        if proc.returncode != 0:
            prog(f"    ! upscayl-bin exited with code {proc.returncode} (falling back to LANCZOS)")
        for _, dst in pairs:
            candidate = out_dir / dst.name
            if candidate.exists():
                shutil.copy2(candidate, dst)
                done.add(dst)
    prog(f"    Upscayl done: {len(done)}/{len(pairs)}")
    return done


                                                                             
                   
                                                                             

def insert_item(items: list[dict], entry: dict) -> None:
    cat = entry["category"]
    idx = [i for i, it in enumerate(items) if it["category"] == cat]
    if idx:
        items.insert(idx[-1] + 1, entry)
    else:
        items.append(entry)


def rename_icon_files(repo_dir: Path, category: str, old: str, new: str) -> None:
    candidates = [old, old.replace("%20", " ")]
    for sub, ext in (("large", "png"), ("small", "png"), ("webp", "webp")):
        dst = repo_dir / sub / category / f"{new}.{ext}"
        if dst.exists():
            continue
        for cand in candidates:
            src = repo_dir / sub / category / f"{cand}.{ext}"
            if src.exists():
                src.rename(dst)
                break


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Rust icons with the repository")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be done")
    parser.add_argument("--regen-all", action="store_true",
                        help="regenerate icons for ALL items found in the game folder")
    parser.add_argument("--items-dir", type=Path, default=None,
                        help=f"game Bundles/items folder ({ENV_ITEMS_DIR})")
    parser.add_argument("--game-dir", type=Path, default=None,
                        help=f"Rust install root ({ENV_GAME_DIR})")
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--upscale-backend", choices=("upscayl", "torch", "none"),
                        default=os.environ.get("RUST_UPSCALE_BACKEND", "upscayl"),
                        help="AI upscale backend: upscayl (Windows), torch (Kaggle/CUDA), none")
    args = parser.parse_args()

                                                                        
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    repo_dir = args.repo_dir.resolve()
    game_dir = resolve_items_dir(args.items_dir, args.game_dir).resolve()
    json_path = repo_dir / "items.json"
    if not json_path.exists():
        print(f"Not found {json_path}", file=sys.stderr)
        return 1
    if not game_dir.exists():
        print(f"Game folder not found: {game_dir}", file=sys.stderr)
        return 1
    if args.dry_run:
        prog("MODE: dry-run (nothing is written)")
    prog(f"Repository: {repo_dir}")
    prog(f"Game folder: {game_dir}")

    items: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))
                                                                     
    by_key = {norm_shortname(it["image_name"]): it for it in items}

                                                                              
    prog("\n[1/4] Reading game items...")
    game_items = load_game_items(game_dir)
    prog(f"    unique items: {len(game_items)}; records in repo: {len(items)}")

                                                                              
    prog("\n[2/4] Reconciling with items.json...")
    icon_queue: list[tuple[str, Path]] = []

    for key in sorted(game_items):
        game = game_items[key]
        category = CATEGORY_MAP.get(game["category"], DEFAULT_CATEGORY)
        if game["category"] not in CATEGORY_MAP:
            log("category_fallback", f"{key}: unknown category {game['category']!r} -> {DEFAULT_CATEGORY}")

        idx = by_key.get(key)
        if idx is not None:
            it = idx

                                
            if it.get("id") != game["itemid"]:
                log("id_fixed", f"{it['image_name']}: {it.get('id')} -> {game['itemid']}")
                prog(f"    id: {it['image_name']} {it.get('id')} -> {game['itemid']}")
                it["id"] = game["itemid"]

                                                                  
            if it["image_name"] != key:
                old = it["image_name"]
                log("renamed", f"{old} -> {key}")
                prog(f"    rename: {old} -> {key}")
                if not args.dry_run:
                    rename_icon_files(repo_dir, it["category"], old, key)
                it["image_name"] = key

                                                                                              
            if game["name"] and game["name"] != it["name"].get("en"):
                old_en = it["name"].get("en")
                log("name_updated", f"{key}: en {old_en!r} -> {game['name']!r} (ru preserved)")
                prog(f"    name: {key}: {old_en!r} -> {game['name']!r}")
                it["name"]["en"] = game["name"]
            continue

                       
        if not game["png"].exists():
            log("skipped_no_icon", f"{key}: {game['png'].name} not found — item not added (no icon)")
            prog(f"    ! {key}: png not found ({game['png'].name}) — skipped")
            continue
        en = game["name"] or key
        entry = {"id": game["itemid"], "image_name": key, "name": {"en": en, "ru": en}, "category": category}
        insert_item(items, entry)
        prog(f"    + [{category}] {key} — {en}")
        log("added", f"[{category}] {key} (id {game['itemid']}): {en}")
        icon_queue.append((key, game["png"]))

                                                                              
                                                                              
    if args.regen_all:
        icon_queue = [
            (it["image_name"], game_items[it["image_name"]]["png"])
            for it in items
            if it["image_name"] in game_items and game_items[it["image_name"]]["png"].exists()
        ]
        no_source = [it["image_name"] for it in items
                     if it["image_name"] not in game_items or not game_items[it["image_name"]]["png"].exists()]
        for name in no_source:
            log("regen_no_source", f"{name}: no source in the game folder — icon not updated")
    prog(f"\n[3/4] Icons: {len(icon_queue)} queued for generation (large+small+webp)...")
    generated = {"large": 0, "small": 0, "webp": 0}
    skipped = 0
    ups_pairs: list[tuple[Path, Path]] = []
    jobs: list[tuple[str, str, Image.Image, Image.Image | None, dict]] = []

    if icon_queue and not args.dry_run:
        for n, (image_name, src_png) in enumerate(icon_queue, 1):
            entry = next((it for it in items if it["image_name"] == image_name), None)
            if entry is None:
                continue
            paths = {
                "large": repo_dir / "large" / entry["category"] / f"{image_name}.png",
                "small": repo_dir / "small" / entry["category"] / f"{image_name}.png",
                "webp": repo_dir / "webp" / entry["category"] / f"{image_name}.webp",
            }
            for p in paths.values():
                p.parent.mkdir(parents=True, exist_ok=True)
            if args.regen_all:
                missing = ["large", "small", "webp"]
            else:
                missing = [k for k, p in paths.items() if not p.exists()]
                if not missing:
                    skipped += 1
                    continue
            src = Image.open(src_png).convert("RGBA")
            src_alpha = src.getchannel("A") if src.getextrema()[3][0] < 255 else None
            small_img = make_small(src, SMALL_SIZE)
            jobs.append((entry["category"], image_name, small_img, src_alpha,
                         {"paths": paths, "missing": missing, "src": src}))
            if n % 50 == 0:
                prog(f"    prepared {n}/{len(icon_queue)}")

                                                  
        with tempfile.TemporaryDirectory(prefix="rust-icons-premul-") as td:
            premul_dir = Path(td) / "premul"
            premul_dir.mkdir()
            final_jobs = []
            for n, (_category, image_name, small_img, src_alpha, meta) in enumerate(jobs, 1):
                paths, missing, src = meta["paths"], meta["missing"], meta["src"]
                if "large" in missing:
                    pm = premultiply_rgba(src)
                    pm_out = premul_dir / f"{image_name}.png"
                    pm.save(pm_out)
                    ups_pairs.append((pm_out, paths["large"]))
                final_jobs.append((image_name, small_img, src_alpha, meta))
                if n % 50 == 0:
                    prog(f"    premultiply {n}/{len(jobs)}")
            ups_done = upscale_batch(ups_pairs, "batch", args.upscale_backend)

            for n, (image_name, small_img, src_alpha, meta) in enumerate(final_jobs, 1):
                paths, missing, src = meta["paths"], meta["missing"], meta["src"]
                if "small" in missing:
                    small_img.save(paths["small"], "PNG", optimize=True)
                    generated["small"] += 1
                if "webp" in missing:
                    small_img.save(paths["webp"], "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
                    generated["webp"] += 1
                if "large" in missing:
                    if paths["large"] in ups_done:
                        up = Image.open(paths["large"])
                        large = finalize_large(up, src_alpha, LARGE_SIZE)
                    else:
                        prog(f"    ! {image_name}: upscale failed, falling back to LANCZOS {src.width}->{LARGE_SIZE}")
                        large = src.resize((LARGE_SIZE, LARGE_SIZE), Image.Resampling.LANCZOS)
                    large.save(paths["large"], "PNG", optimize=True)
                    generated["large"] += 1
                if n % 50 == 0:
                    prog(f"    done {n}/{len(final_jobs)}")
        prog(f"    total: large={generated['large']}, small={generated['small']}, webp={generated['webp']}, already present: {skipped}")
    elif icon_queue:
        prog("    [dry-run] icon generation skipped")
    else:
        prog("    everything up to date")

                                                                              
    prog("\n[4/4] Writing items.json...")
    items = [it for it in items if it is not None]
    if not args.dry_run:
        text = json.dumps(items, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        json_path.write_bytes(text.encode("utf-8"))
        prog(f"    wrote {len(items)} records -> {json_path.name}")
    else:
        prog("    [dry-run] json not written")

    prog("\n" + "=" * 60)
    prog("REPORT" + ("  (dry-run — nothing written)" if args.dry_run else ""))
    prog("=" * 60)
    for section in ("added", "id_fixed", "renamed", "name_updated", "skipped_no_icon", "regen_no_source",
                    "category_fallback", "itemid_conflicts", "game_json_errors"):
        rows = report.get(section, [])
        if not rows:
            continue
        prog(f"\n{section} ({len(rows)}):")
        for line in rows:
            prog(f"  - {line}")
    prog("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
