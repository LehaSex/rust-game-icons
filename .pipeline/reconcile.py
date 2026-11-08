from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ICON_SETS = (("large", "png"), ("small", "png"), ("webp", "webp"))


def norm_shortname(s: str) -> str:
    return (s or "").replace("%20", " ").replace(" ", ".").strip()


def load_item_defs(items_bundle: Path, log=print) -> dict[str, int] | None:
    try:
        import UnityPy
    except ImportError:
        log("  ! UnityPy is not installed — falling back to json-based reconciliation")
        return None
    try:
        bundle = UnityPy.load(str(items_bundle))
    except Exception as exc:
        log(f"  ! cannot read {items_bundle}: {exc} — falling back to json-based reconciliation")
        return None
    registry: dict[str, int] = {}
    for obj in bundle.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            d = obj.read_typetree()
        except Exception:
            continue
        if isinstance(d, dict) and d.get("shortname") and d.get("itemid") is not None:
            registry[str(d["shortname"]).strip()] = d["itemid"]
    if not registry:
        log("  ! no item definitions parsed from the bundle — reconciliation skipped")
        return None
    return registry


def rename_icon_files(repo_dir: Path, category: str, old: str, new: str) -> int:
    candidates = {old, old.replace("%20", " ")}
    moved = 0
    for sub, ext in ICON_SETS:
        dst = repo_dir / sub / category / f"{new}.{ext}"
        if dst.exists():
            continue
        for cand in candidates:
            src = repo_dir / sub / category / f"{cand}.{ext}"
            if src.exists():
                src.rename(dst)
                moved += 1
                break
    return moved


def delete_icon_files(repo_dir: Path, category: str, name: str) -> int:
    removed = 0
    for sub, ext in ICON_SETS:
        p = repo_dir / sub / category / f"{name}.{ext}"
        if p.exists():
            p.unlink()
            removed += 1
    return removed


def move_icon_files(repo_dir: Path, old_category: str, old: str,
                    new_category: str, new: str) -> str:
    result = "dropped"
    for sub, ext in ICON_SETS:
        src = repo_dir / sub / old_category / f"{old}.{ext}"
        if not src.exists():
            continue
        dst = repo_dir / sub / new_category / f"{new}.{ext}"
        if dst.exists():
            src.unlink()
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            result = "moved"
    return result


def plan(items: list[dict], game: dict[str, dict],
         active: dict[str, int]) -> tuple[list[dict], dict[str, str]]:
    game_keys = set(game)

    by_key = {norm_shortname(i["image_name"]): i for i in items if i.get("image_name")}
    by_id: dict[object, list[dict]] = {}
    for i in items:
        if i.get("id") is not None:
            by_id.setdefault(i["id"], []).append(i)
    game_ids = Counter(e["itemid"] for e in game.values() if e.get("itemid") is not None)
    unique_game_key = {e["itemid"]: k for k, e in game.items()
                       if e.get("itemid") is not None and game_ids[e["itemid"]] == 1}

    # Live keys per the registry: the pair (raw shortname, itemid) exists.
    live = {k for k, e in game.items()
            if active.get(str(e.get("raw") or e.get("shortname") or "")) == e.get("itemid")}

    def heir(iid: object) -> str | None:
        heirs = sorted(norm_shortname(s) for s, j in active.items() if j == iid)
        return heirs[0] if len(heirs) == 1 else None

    # Legacy alias json files: every entry the registry does not confirm.
    dead: dict[str, str] = {}
    for k, e in sorted(game.items()):
        if k in live:
            continue
        iid = e.get("itemid")
        canon = None if iid is None else heir(iid)
        if canon is None:
            if active is not None and iid is not None and iid not in set(active.values()):
                # The itemid is not in the registry at all: the item was
                # retired from the game outright. Do not ship it anywhere.
                dead[k] = ""
                continue
            if iid is not None:
                print(f"  ! {k}: no unambiguous heir for itemid {iid} — left as is")
            continue
        dead[k] = canon

    renames: dict[int, dict] = {}
    ops: list[dict] = []

    # 1. dead legacy keys ("mini fridge" -> "mini.fridge" beside "minifridge")
    # and retired items (no heir at all -> target ""). The record under the
    # dead key belongs to the canonical one: rename it there when the
    # canonical record does not exist yet, otherwise remove the duplicate.
    for d_key in sorted(dead):
        r = by_key.get(d_key)
        if r is None or id(r) in renames:
            continue
        canon = dead[d_key]
        if canon == "" or canon in by_key:
            ops.append({"op": "delete", "record": r, "target": canon})
        else:
            ops.append({"op": "rename", "record": r, "key": canon})
            renames[id(r)] = ops[-1]

    # 2. shortname changed, same id -> rename the record in place
    for key in sorted(game_keys):
        if key in by_key or key in dead:
            continue
        itemid = game[key].get("itemid")
        if itemid is None or game_ids[itemid] != 1:
            continue
        cands = [r for r in by_id.get(itemid, [])
                 if r is not None and norm_shortname(r["image_name"]) not in game_keys]
        if len(cands) != 1:
            continue
        ops.append({"op": "rename", "record": cands[0], "key": key})
        renames[id(cands[0])] = ops[-1]

    # 3. stale records: shortname is gone from the game but the id lives on
    for r in items:
        if id(r) in renames:
            continue
        key = norm_shortname(r.get("image_name") or "")
        if not key or key in game_keys:
            continue
        itemid = r.get("id")
        target = None if itemid is None else unique_game_key.get(itemid)
        if itemid is not None and itemid not in active.values():
            # the registry has no such id — the item is not simply renamed,
            # do not guess; such cases (retired/changed ids) are rare
            continue
        if target is None:
            continue
        occupied = any(
            norm_shortname(x.get("image_name") or "") == target
            for x in items if x is not r
        )
        if occupied:
            ops.append({"op": "delete", "record": r, "target": target})
        else:
            print(f"  ! {key}: id {r.get('id')} belongs to `{target}` but no record "
                  "nor rename covers it — left untouched")
    return ops, dead


def apply(items: list[dict], ops: list[dict], repo_dir: Path | None = None,
          dry_run: bool = False, log=print) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"renamed_by_id": [], "removed_stale": []}

    for op in ops:
        r = op["record"]
        if op["op"] == "rename":
            key = op["key"]
            old = r["image_name"]
            if norm_shortname(old) == key:
                continue
            log(f"    rename: {old} -> {key} (same id {r.get('id')})")
            report["renamed_by_id"].append(f"{old} -> {key}")
            if not dry_run and repo_dir is not None:
                rename_icon_files(repo_dir, str(r.get("category")), old, key)
            r["image_name"] = key

    for op in reversed(ops):
        if op["op"] != "delete":
            continue
        r = op["record"]
        key = norm_shortname(r.get("image_name") or "")
        target = op["target"]
        keep = next((x for x in items if x is not r
                     and norm_shortname(x.get("image_name") or "") == target), None)
        log(f"    stale: {key} (id {r.get('id')}) — now `{target}`, record removed")
        report["removed_stale"].append(f"{key} -> {target}")
        if not dry_run and repo_dir is not None:
            if keep is None:
                delete_icon_files(repo_dir, str(r.get("category")), key)
            else:
                move_icon_files(repo_dir, str(r.get("category")), key,
                                str(keep.get("category")), target)
        items.remove(r)

    return report


def print_report(report: dict[str, list[str]], log=print) -> None:
    for section, lines in report.items():
        if not lines:
            continue
        log(f"  {section} ({len(lines)}):")
        for line in lines:
            log(f"    - {line}")


def summary_lines(report: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for section, lines in report.items():
        if not lines:
            continue
        out.append(f"### {section}\n")
        out.append("| old | new |")
        out.append("|---|---|")
        for line in lines:
            old, _, new = line.partition(" -> ")
            out.append(f"| `{old}` | `{new}` |")
        out.append("")
    return out


def reconcile_items(items_path: Path, game: dict[str, dict], repo_dir: Path | None = None,
                    active: dict[str, int] | None = None,
                    log=print) -> tuple[dict[str, list[str]], dict[str, str]]:
    items = json.loads(items_path.read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", [])
    ops, dead = (plan(items, game, active=active) if active is not None else ([], {}))
    if not ops:
        log("  reconcile: nothing to rename or remove")
        return {}, dead
    report = apply(items, ops, repo_dir=repo_dir, log=log)
    if any(report.values()):
        log(f"  reconcile: writing {items_path.name} ({len(items)} records)")
        items_path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print_report(report, log)
    return report, dead
