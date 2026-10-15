                      

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

                            
STEPS = {
    "localization": ("extract_localization.py", "unpack the game localization"),
    "icons": ("sync_icons.py", "items and icons"),
    "translations": ("sync_translations.py", "translations and items.compact.json"),
    "craft": ("extract_crafting.py", "items.craft.json"),
    "recycle": ("extract_recycle.py", "items.recycle.json"),
    "untranslated": ("find_untranslated.py", "report on untranslated items"),
}
STEP_ORDER = list(STEPS)

                                                                          
                                                                            
            
STEP_ARGS: dict[str, set[str]] = {
    "extract_localization.py": {"--game-dir", "--bundle"},
    "extract_crafting.py": {"--game-dir", "--items-bundle", "--content-bundle"},
    "extract_recycle.py": {"--game-dir", "--items-bundle", "--content-bundle"},
    "sync_icons.py": {"--game-dir", "--items-dir", "--repo-dir", "--upscale-backend"},
    "sync_translations.py": {"--repo-dir", "--loc-dir"},
    "find_untranslated.py": {"--repo-dir", "--out", "--category"},
}


def build_cmd(step: str, args: argparse.Namespace) -> list[str]:
    script = STEPS[step][0]
    cmd = [sys.executable, str(SCRIPT_DIR / script)]
    allowed = STEP_ARGS.get(script, set())

    def add(flag: str, value: object) -> None:
        if value and flag in allowed:
            cmd.extend([flag, str(value)])

    if step == "localization":
        add("--bundle", args.content_bundle)
    else:
        add("--items-bundle", args.items_bundle)
        add("--content-bundle", args.content_bundle)
    add("--game-dir", args.game_dir)
    add("--items-dir", args.items_dir)
    add("--repo-dir", args.repo_dir)
    add("--upscale-backend", args.upscale_backend)

    if args.dry_run and step in ("icons", "translations"):
        cmd.append("--dry-run")
    if args.overwrite and step == "translations":
        cmd.append("--mode", "overwrite")
    if args.regen_icons and step == "icons":
        cmd.append("--regen-all")
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Full refresh of Rust item data from the game folder.")
    parser.add_argument("--only", default=None,
                        help=f"only these steps, comma-separated ({', '.join(STEP_ORDER)})")
    parser.add_argument("--skip", default=None, help="skip these steps, comma-separated")
    parser.add_argument("--dry-run", action="store_true", help="write no files (icons, translations)")
    parser.add_argument("--overwrite", action="store_true", help="overwrite en/ru with in-game translations")
    parser.add_argument("--regen-icons", action="store_true", help="regenerate ALL icons (slow)")
    parser.add_argument("--items-bundle", default=None, help="path to items.preload.bundle")
    parser.add_argument("--content-bundle", default=None, help="path to content.bundle")
    parser.add_argument("--game-dir", type=Path, default=None, help="Rust install root")
    parser.add_argument("--items-dir", type=Path, default=None, help="game Bundles/items folder")
    parser.add_argument("--upscale-backend", default=None,
                        choices=("upscayl", "torch", "none"),
                        help="AI upscale backend (default RUST_UPSCALE_BACKEND or upscayl)")
    parser.add_argument("--repo-dir", type=Path, default=None, help="icon repository root")
    args = parser.parse_args()

    steps = list(STEP_ORDER)
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in STEPS]
        if unknown:
            sys.exit(f"unknown steps: {unknown}; available: {STEP_ORDER}")
        steps = [s for s in STEP_ORDER if s in wanted]
    if args.skip:
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        unknown = [s for s in skip if s not in STEPS]
        if unknown:
            sys.exit(f"unknown steps: {unknown}; available: {STEP_ORDER}")
        steps = [s for s in steps if s not in skip]

    if args.regen_icons:
        print("!! --regen-icons: every existing icon will be regenerated from scratch")

    failed = []
    for i, step in enumerate(steps, 1):
        print(f"\n=== [{i}/{len(steps)}] {step}: {STEPS[step][1]} ===", flush=True)
        cmd = build_cmd(step, args)
        print("  $ " + " ".join(cmd), flush=True)
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"!! step {step} failed with code {rc}", flush=True)
            failed.append(step)
            if step in ("localization", "icons", "translations"):
                                                                            
                break

    print("\n=== summary ===")
    print("ok:   " + ", ".join(s for s in steps if s not in failed) if steps else "ok:   —")
    if failed:
        print("fail: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())