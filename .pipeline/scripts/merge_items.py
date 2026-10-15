"""Add the items from a staged delta to items.json.

The Kaggle kernel returns icons only; nothing downstream ever wrote the new
records, so without this the repository never learns an item exists and the
next delta computation asks for the same icons again.

Input is the `needed.json` that stage_delta.py produced -- shortname, itemid,
name and category for every item that was missing from the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CATEGORY_MAP = {
    "ammunition": "ammo", "attire": "attire", "component": "components",
    "construction": "construction", "electrical": "electrical", "food": "food",
    "fun": "fun", "items": "items", "medical": "medical", "misc": "misc",
    "resources": "resources", "tool": "tools", "tools": "tools",
    "traps": "traps", "weapon": "weapons", "weapons": "weapons",
}
DEFAULT_CATEGORY = "items"

VALID = {"ammo", "attire", "components", "construction", "electrical", "food",
         "fun", "items", "medical", "misc", "resources", "tools", "traps", "weapons"}


def normalize_category(raw: object) -> str:
    if not isinstance(raw, str):
        return DEFAULT_CATEGORY
    key = raw.strip().lower()
    mapped = CATEGORY_MAP.get(key, key if key in VALID else DEFAULT_CATEGORY)
    return mapped if mapped in VALID else DEFAULT_CATEGORY


def load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"{path}: no item list found")
    return items


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Merge delta items into items.json")
    ap.add_argument("--repo-dir", type=Path, default=Path("."))
    ap.add_argument("--needed", type=Path, required=True, help="needed.json from stage_delta.py")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="kernel manifest.json; when given, only items it actually wrote are merged")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    items_path = args.repo_dir / "items.json"
    if not items_path.is_file():
        raise SystemExit(f"not found: {items_path}")
    items = load_items(items_path)

    delta = json.loads(args.needed.read_text(encoding="utf-8"))
    wanted = delta.get("items", []) if isinstance(delta, dict) else delta

    only: set[str] | None = None
    if args.manifest and args.manifest.is_file():
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        produced = man.get("items")
        if produced:
            only = set(produced)
            print(f"kernel wrote {len(only)} icon(s); the rest are left for the next run")
        else:
            only = None

    known = {i.get("image_name") for i in items}
    added: list[dict] = []
    for entry in wanted:
        key = entry.get("shortname")
        if not key or key in known:
            continue
        if only is not None and key not in only:
            continue
        en = entry.get("name") or key
        record = {
            "id": entry.get("itemid"),
            "image_name": key,
            "name": {"en": en, "ru": en},
            "category": normalize_category(entry.get("category")),
        }
        added.append(record)
        known.add(key)

    if not added:
        print("nothing to add; items.json is unchanged")
        return 0

    by_category: dict[str, int] = {}
    for record in added:
        by_category[record["category"]] = by_category.get(record["category"], 0) + 1

    if not args.dry_run:
        items.extend(added)
        items_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"+{len(added)} item(s): " + ", ".join(f"{c}={n}" for c, n in sorted(by_category.items())))
    for record in added[:12]:
        print(f"  + [{record['category']}] {record['image_name']} - {record['name']['en']}")
    if len(added) > 12:
        print(f"  ... and {len(added) - 12} more")
    print(f"items.json: {len(items) - len(added)} -> {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())