
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".pipeline"
try:
    import jsonschema
except ImportError:
    jsonschema = None

DATA_FILES = ["items.json", "items.compact.json", "items.desc.json",
              "items.craft.json", "items.recycle.json"]
SCHEMAS = {
    "items.json": "items.schema.json",
    "items.compact.json": "items.compact.schema.json",
}
LARGE_SIZE = 1080
SMALL_SIZE = 180
CATEGORIES = {"ammo", "attire", "components", "construction", "electrical", "food",
              "fun", "items", "medical", "misc", "resources", "tools", "traps", "weapons"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def print(self) -> None:
                                                                               
                                                                   
        for n in self.notes:
            print(f"  · {n}")
        for w in self.warnings:
            print(f"  ! {w}")
        for e in self.errors:
            print(f"  x {e}")


def load(repo: Path, name: str, rep: Report):
    path = repo / name
    if not path.is_file():
        rep.err(f"missing file {name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.err(f"{name} does not parse: {exc}")
        return None


def as_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def as_keys(data) -> dict:
    if isinstance(data, dict):
        if isinstance(data.get("items"), dict):
            return data["items"]
        return data
    if isinstance(data, list):
        return {i.get("image_name") or i.get("shortname"): i for i in data if isinstance(i, dict)}
    return {}


def check_schemas(repo: Path, rep: Report) -> None:
    if jsonschema is None:
        rep.warn("jsonschema is not installed, schema validation skipped (pip install jsonschema)")
        return
    for data_name, schema_name in SCHEMAS.items():
        schema_path = PIPELINE / "schemas" / schema_name
        if not schema_path.is_file():
            rep.warn(f"no schema {schema_name}")
            continue
        data = load(repo, data_name, rep)
        if data is None:
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(data, schema)
            rep.note(f"schema {data_name}: ok")
        except jsonschema.ValidationError as exc:
            rep.err(f"{data_name} fails the schema: {exc.message} (path {list(exc.absolute_path)[:3]})")


def check_keys(items, craft, recycle, rep: Report) -> None:
    names = {i["image_name"] for i in items if i.get("image_name")}
    rep.note(f"items in items.json: {len(names)}")
    for label, table in (("items.craft.json", as_keys(craft)), ("items.recycle.json", as_keys(recycle))):
        if not table:
            rep.err(f"{label} is empty or unreadable")
            continue
        missing = names - set(table)
        if missing:
                                                                            
                                                                                   
            sample = sorted(missing)[:5]
            rep.warn(f"{label}: no record for {len(missing)} items, for example {sample}")
        else:
            rep.note(f"{label}: covers every item")


def check_compact(compact, rep: Report) -> None:
    items = as_items(compact)
    if not items:
        rep.err("items.compact.json is empty")
        return
    bad = []
    for i in items[:50]:
        keys = list(i.get("name", {}).keys())
        if keys != ["en", "zh-cn", "ru"]:
            bad.append((i.get("image_name"), keys))
            break
    if bad:
        rep.err(f"items.compact.json: language set or order is wrong: {bad[0]}")


def check_icons(repo: Path, items, rep: Report) -> None:
    names = {i["image_name"] for i in items if i.get("image_name")}
    by_cat = {i["category"]: i["image_name"] for i in items if i.get("image_name")}

    for sub, size in (("small", SMALL_SIZE), ("large", LARGE_SIZE)):
        base = repo / sub
        if not base.is_dir():
            rep.warn(f"no {sub}/ folder — check skipped")
            continue
        missing = 0
        for i in items:
            name = i.get("image_name")
            if not name:
                continue
            if not (base / i["category"] / f"{name}.png").is_file():
                missing += 1
        if missing:
            rep.err(f"{sub}/: no file for {missing} items")
        else:
            rep.note(f"{sub}/: all {len(items)} items present")

    orphans = 0
    large = repo / "large"
    if large.is_dir():
        for cat_dir in large.iterdir():
            if not cat_dir.is_dir():
                continue
            for png in cat_dir.glob("*.png"):
                if png.stem not in names:
                    orphans += 1
        if orphans:
            rep.warn(f"large/: {orphans} icons with no item in items.json (4 are known historical ones)")

    wrong_size = 0
    try:
        from PIL import Image
    except ImportError:
        return
    for sub, size in (("small", SMALL_SIZE), ("large", LARGE_SIZE)):
        base = repo / sub
        if not base.is_dir():
            continue
        wrong = 0
        for cat_dir in base.iterdir():
            if not cat_dir.is_dir():
                continue
            for png in list(cat_dir.glob("*.png"))[:50]:
                try:
                    with Image.open(png) as im:
                        if im.size != (size, size):
                            wrong += 1
                except Exception:
                    wrong += 1
        if wrong:
            rep.err(f"{sub}/: {wrong} files are not {size}x{size} or are corrupt")
        wrong_size += wrong


def baseline_json(repo: Path, name: str, baseline: str) -> object | None:
    try:
        raw = subprocess.run(["git", "show", f"{baseline}:{name}"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    except Exception as exc:
        rep_note = f"could not read {baseline}:{name} ({exc})"
        return rep_note
    if raw.returncode != 0:
        return f"could not read {baseline}:{name}"
    try:
        return json.loads(raw.stdout)
    except Exception as exc:
        return f"{name} in {baseline} does not parse ({exc})"


def check_shrinkage(repo: Path, rep: Report, baseline: str | None, tolerance: float) -> None:
    """A broken extractor produces valid JSON that is simply missing things.

    Schema checks and key coverage both pass on a table that quietly lost half
    its rows, so the row counts are compared against the baseline explicitly.
    """
    if not baseline:
        return
    tables = ("items.json", "items.compact.json", "items.craft.json",
              "items.recycle.json", "items.desc.json")
    for name in tables:
        current = load(repo, name, rep)
        if current is None:
            continue
        old = baseline_json(repo, name, baseline)
        if isinstance(old, str):
            rep.warn(old)
            continue
        if old is None:
            continue
        was = len(as_items(old)) if name in ("items.json", "items.compact.json") else len(as_keys(old))
        now = len(as_items(current)) if name in ("items.json", "items.compact.json") else len(as_keys(current))
        lost = was - now
        allowed = max(1, int(was * tolerance))
        if lost > allowed:
            rep.err(f"{name}: lost {lost} record(s), {was} -> {now} (tolerance {allowed}); "
                    "a broken extractor usually looks like this")
        elif lost > 0:
            rep.note(f"{name}: {was} -> {now} ({lost} fewer, within tolerance)")
        else:
            rep.note(f"{name}: {was} -> {now}")


def check_translation_regression(repo: Path, items, baseline: str | None, rep: Report) -> None:
    def untranslated_map(lst: list[dict]) -> dict[str, bool]:
        return {i.get("image_name"): i.get("name", {}).get("ru", "") == i.get("name", {}).get("en", "")
                for i in lst if i.get("image_name")}

    now = untranslated_map(items)
    n_un = sum(1 for v in now.values() if v)
    total = len(items)
    rep.note(f"ru == en for {n_un} of {total} items ({100.0 * n_un / max(total, 1):.1f}%)")
    if not baseline:
        return
    try:
        raw = subprocess.run(["git", "show", f"{baseline}:items.json"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        if raw.returncode != 0:
            rep.warn(f"could not read {baseline}:items.json")
            return
        before = as_items(json.loads(raw.stdout))
    except Exception as exc:
        rep.warn(f"could not read the baseline: {exc}")
        return
    was = untranslated_map(before)

    lost = sorted(k for k, un in was.items() if not un and now.get(k, False))
    gained = sorted(k for k, un in now.items() if un and k not in was)
    if lost:
        rep.err(f"translation regression: {len(lost)} items lost their ru translation: {', '.join(lost[:5])}")
    elif gained:
        rep.warn(f"{len(gained)} new items without ru for now: {', '.join(gained[:5])}")
    else:
        rep.note("translations did not get worse")


def check_delta(out: Path, repo: Path, rep: Report) -> None:
    if not out.is_dir():
        return
    man = out / "manifest.json"
    if not man.is_file():
        rep.warn("no out/manifest.json — the delta was not parsed")
        return
    data = json.loads(man.read_text(encoding="utf-8"))
    got = data.get("count", 0)
    req = data.get("requested", got)
    rep.note(f"delta: requested {req}, upscaled {data.get('upscaled', 0)}, wrote {got}")
    if req and got < req:
        rep.warn(f"wrote fewer than requested: {got} of {req}")
    icons = out / "icons"
    if not icons.is_dir():
        rep.err("no icons folder in out/")
        return
    for sub in ("large", "small", "webp"):
        n = len(list((icons / sub).rglob("*"))) if (icons / sub).is_dir() else 0
        rep.note(f"icons/{sub}: {n} files")
    dupes = []
    for png in (icons / "large").rglob("*.png") if (icons / "large").is_dir() else []:
        if (repo / "large").is_dir() and any((repo / "large").rglob(png.name)):
            dupes.append(png.name)
    if dupes:
        rep.err(f"the delta overwrote existing icons: {dupes[:5]}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Validate pipeline artifacts")
    ap.add_argument("--repo-dir", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None, help="Kaggle kernel output directory")
    ap.add_argument("--baseline", default="main", help="branch to compare translations against")
    ap.add_argument("--shrink-tolerance", type=float, default=0.005,
                    help="fraction of records a table may lose before it counts as an error "
                         "(default 0.5%%; a real patch adds items, never removes them)")
    args = ap.parse_args()

    repo = args.repo_dir.resolve()
    rep = Report()

    print(f"validating {repo}")
    items_data = load(repo, "items.json", rep)
    if items_data is None:
        rep.print()
        return 1
    items = as_items(items_data)

    unknown = {i.get("category") for i in items} - CATEGORIES
    if unknown:
        rep.err(f"unknown categories in items.json: {sorted(unknown)}")

    for name in DATA_FILES:
        if name != "items.json":
            load(repo, name, rep)

    check_schemas(repo, rep)
    check_keys(items, load(repo, "items.craft.json", rep), load(repo, "items.recycle.json", rep), rep)
    check_compact(load(repo, "items.compact.json", rep), rep)
    check_icons(repo, items, rep)
    check_translation_regression(repo, items, args.baseline, rep)
    check_shrinkage(repo, rep, args.baseline, args.shrink_tolerance)
    if args.out:
        check_delta(args.out.resolve(), repo, rep)

    rep.print()
    print(f"\n{len(rep.errors)} errors, {len(rep.warnings)} warnings")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())