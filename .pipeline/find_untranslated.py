                      

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_DIR = SCRIPT_DIR.parent
DEFAULT_OUT = SCRIPT_DIR / "missing" / "ru.txt"


def main() -> int:
    parser = argparse.ArgumentParser(description="List items without a Russian translation")
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output file for the list ('-' — console only)")
    parser.add_argument("--category", default=None, help="filter by repository category (ammo, tools, ...)")
    args = parser.parse_args()

                                                                        
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    json_path = args.repo_dir.resolve() / "items.json"
    if not json_path.exists():
        print(f"Not found {json_path}", file=sys.stderr)
        return 1

    items: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))

    missing = [
        it for it in items
        if not it["name"].get("ru") or it["name"]["ru"].strip() == it["name"]["en"].strip()
    ]
    if args.category:
        missing = [it for it in missing if it["category"] == args.category]

    if not missing:
        print("All items are translated.")
        return 0

    by_cat = Counter(it["category"] for it in missing)
    print(f"Items without a translation: {len(missing)} (of {len(items)} records)\n")
    for cat in sorted(by_cat):
        print(f"  {cat}: {by_cat[cat]}")

    if args.out != Path("-"):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="\r\n") as f:
            f.write("# Format: shortname<TAB>english name\n")
            for it in sorted(missing, key=lambda x: (x["category"], x["image_name"])):
                f.write(f"{it['image_name']}\t{it['name']['en']}\n")
        print(f"\nList saved to: {args.out}")
    else:
        for it in sorted(missing, key=lambda x: (x["category"], x["image_name"])):
            print(f"{it['image_name']}\t{it['name']['en']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
