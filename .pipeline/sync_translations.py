                      

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_DIR = SCRIPT_DIR.parent
DEFAULT_LOC_DIR = SCRIPT_DIR / "localization"
BASE_LANG = "en"
COMPACT_LANGS = ("en", "zh-cn", "ru")

report: dict[str, list] = {}


def prog(msg: str) -> None:
    print(msg, flush=True)


def log(section: str, line: str) -> None:
    report.setdefault(section, []).append(line)


def norm_shortname(s: str) -> str:
    return s.replace("%20", " ").replace(" ", ".").strip().lower()


def candidate_keys(shortname: str, en_name: str) -> list[str]:
    n = norm_shortname(shortname)
    legacy = re.sub(r"\s+", " ", en_name.strip().lower())
    keys = [
        n,
        n + ".name",
        n.replace(".", " "),
        legacy,
        n.replace(".", "").replace("_", ""),
        legacy.replace(" ", "_"),
    ]
    seen: set[str] = set()
    return [k for k in keys if k and not (k in seen or seen.add(k))]


def desc_keys(shortname: str, en_name: str) -> list[str]:
    n = norm_shortname(shortname)
    legacy = re.sub(r"\s+", " ", en_name.strip().lower())
    keys = [
        n + ".desc",
        n.replace(".", " ") + ".desc",
        legacy + ".desc",
        legacy.replace(" ", ".") + ".desc",
        legacy.replace(" ", "_") + ".desc",
        n.replace(".", "").replace("_", "") + ".desc",
    ]
    seen: set[str] = set()
    return [k for k in keys if k and not (k in seen or seen.add(k))]


def load_lang(loc_dir: Path, lang: str) -> dict[str, str]:
    path = loc_dir / lang / "engine.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def dump_json(items: list[dict], path: Path) -> None:
    text = json.dumps(items, ensure_ascii=False, indent=2).replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync translations into items.json and items.compact.json")
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--loc-dir", type=Path, default=DEFAULT_LOC_DIR)
    parser.add_argument("--mode", choices=("fill", "overwrite"), default="fill",
                        help="fill — keep manual translations (default); overwrite — replace with in-game ones")
    parser.add_argument("--langs", default=None,
                        help="comma-separated languages (default: all from automation/localization)")
    parser.add_argument("--dry-run", action="store_true", help="do not write files")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    repo_dir = args.repo_dir.resolve()
    json_path = repo_dir / "items.json"
    compact_path = repo_dir / "items.compact.json"
    desc_path = repo_dir / "items.desc.json"
    if not json_path.exists():
        prog(f"Not found {json_path}")
        return 1
    items: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))
    prog(f"Items in items.json: {len(items)}")

    skip = {"editor", "ui"}
    if args.langs is None:
        langs = [p.name for p in sorted(args.loc_dir.iterdir())
                 if p.is_dir() and p.name not in skip and (p / "engine.json").is_file()]
    else:
        langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    langs = [BASE_LANG] + [l for l in langs if l != BASE_LANG]
    langs = list(dict.fromkeys(langs))

    tables: dict[str, dict[str, str]] = {}
    for lang in langs:
        table = load_lang(args.loc_dir, lang)
        if not table:
            prog(f"No localization for '{lang}' in {args.loc_dir} — run extract_localization.py first")
            return 1
        tables[lang] = table
        prog(f"    {lang}: {len(table)} keys")
    en_table = tables[BASE_LANG]

    filled = {lang: 0 for lang in langs}
    updated = {lang: 0 for lang in langs}
    fallback = {lang: 0 for lang in langs}
    unresolved: dict[str, dict[str, str]] = {lang: {} for lang in langs}

    for it in items:
        sn = it["image_name"]
        name = it.setdefault("name", {})
        en_name = name.get("en", "")

        keys = candidate_keys(sn, en_name)
        key = next((k for k in keys if k in en_table), None)
        if key is None:
            for lang in langs[1:]:
                alt = next((k for k in keys if k in tables[lang]), None)
                if alt:
                    key = alt
                    break
        if key is None:
            for lang in langs:
                if lang != BASE_LANG and not name.get(lang, "").strip():
                    name[lang] = en_name
                    fallback[lang] += 1
                unresolved[lang][sn] = name.get(lang) or en_name
            continue

        for lang in langs:
            game_val = tables[lang].get(key)
            if not game_val:
                if lang != BASE_LANG and not name.get(lang, "").strip():
                    name[lang] = en_name
                    fallback[lang] += 1
                unresolved[lang][sn] = name.get(lang) or en_name
                continue

            current = name.get(lang, "")
            is_new = not current.strip()
            is_placeholder = lang == "ru" and current.strip() == en_name.strip()

            if lang in ("en", "ru"):
                                                                                    
                should = (is_new or is_placeholder) if args.mode == "fill" else True
            else:
                                                                                      
                should = True

            if not should:
                continue
            if current == game_val:
                continue
            name[lang] = game_val
            if is_new or is_placeholder:
                filled[lang] += 1
            else:
                updated[lang] += 1

    for lang in langs:
        prog(f"{lang}: filled {filled[lang]}, updated {updated[lang]}, "
             f"en fallback {fallback[lang]}, absent from the game localization {len(unresolved[lang])}")

    if args.dry_run:
        prog("Dry-run: no files written")
        return 0

    dump_json(items, json_path)
    prog(f"Wrote {json_path} ({json_path.stat().st_size:,} bytes)")

    compact: list[dict] = []
    for it in items:
        name = it["name"]
        en = name.get(BASE_LANG, "")
        c = {lang: name.get(lang) or en for lang in COMPACT_LANGS}
        compact.append({**it, "name": c})
    dump_json(compact, compact_path)
    compact_langs: dict[str, int] = {}
    for it in compact:
        for lang in it["name"]:
            compact_langs[lang] = compact_langs.get(lang, 0) + 1
    prog(f"Wrote {compact_path.name} ({compact_path.stat().st_size:,} bytes): "
         + ", ".join(f"{k}={v}" for k, v in compact_langs.items()))

    desc_out: dict[str, dict[str, str]] = {}
    no_desc = 0
    for it in items:
        sn = it["image_name"]
        en_name = it["name"].get("en", "")
        dkey = next((k for k in desc_keys(sn, en_name) if k in en_table), None)
        if dkey is None:
            no_desc += 1
            continue
        en_desc = en_table[dkey]
        desc_out[sn] = {lang: tables[lang].get(dkey) or en_desc for lang in langs}
    dump_json(desc_out, desc_path)
    prog(f"Wrote {desc_path.name} ({desc_path.stat().st_size:,} bytes): "
         f"descriptions for {len(desc_out)} of {len(items)} items, without description {no_desc}")

    missing_dir = SCRIPT_DIR / "missing"
    missing_dir.mkdir(exist_ok=True)
    for lang in langs:
        mpath = missing_dir / f"{lang}.txt"
        missing = unresolved[lang]
        if not missing:
            if mpath.exists():
                mpath.unlink()
                prog(f"Removed {mpath.relative_to(repo_dir)} — no gaps left")
            continue
        with mpath.open("w", encoding="utf-8", newline="\r\n") as f:
            f.write("# Format: shortname<TAB>english name\n")
            for shortname, label in sorted(missing.items()):
                f.write(f"{shortname}\t{label}\n")
        prog(f"Gaps {lang}: {mpath.relative_to(repo_dir)} ({len(missing)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
