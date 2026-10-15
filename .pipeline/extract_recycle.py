                      

import argparse
import json
import sys
from pathlib import Path

from paths import (
    ENV_CONTENT_BUNDLE,
    ENV_ITEMS_BUNDLE,
    ENV_GAME_DIR,
    content_bundle,
    items_bundle,
    require_file,
)

try:
    import UnityPy
except ImportError:
    sys.exit("UnityPy is not installed. Run: pip install UnityPy")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR.parent / "items.recycle.json"

                                                      
RATE_BY_TYPE = {0: "monument", 1: "safe_zone", 2: "power_plant"}


def normalize_name(s: str) -> str:
    return s.replace("%20", " ").replace(" ", ".").strip()


def pptr_name(af_by_cab, defs_by_path, src_af, pptr):
    fid = pptr["m_FileID"]
    if fid == 0:
        t = defs_by_path.get(pptr["m_PathID"])
        return t["shortname"] if t else None
    ext = src_af.externals[fid - 1]
    target_af = af_by_cab.get(ext.name)
    if target_af is None:
        return None
    t = defs_by_path.get(pptr["m_PathID"])
    return t["shortname"] if t else None


def round_val(v):
    v = round(v, 2)
    return int(v) if v == int(v) else v


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Rust item recycling data to items.recycle.json.")
    parser.add_argument("--game-dir", default=None,
                        help=f"Rust install root ({ENV_GAME_DIR})")
    parser.add_argument("--items-bundle", default=None,
                        help=f"items.preload.bundle (env {ENV_ITEMS_BUNDLE} or --game-dir)")
    parser.add_argument("--content-bundle", default=None,
                        help=f"content.bundle (env {ENV_CONTENT_BUNDLE} or --game-dir)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output json path")
    args = parser.parse_args()

    items_path = require_file(items_bundle(args.items_bundle), "items.preload.bundle")
    content_path = require_file(content_bundle(args.content_bundle), "content.bundle")

                                                           
    env = UnityPy.load(items_path)
    defs_by_path = {}
    short_by_go = {}
    bp_by_go = {}
    scripts_by_path = {}
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            scripts_by_path[obj.path_id] = obj.read().m_ClassName
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        af = obj.assets_file
        tree = obj.read_typetree()
        if not isinstance(tree, dict):
            continue
        go = tree["m_GameObject"]["m_PathID"]
        cls = scripts_by_path.get(tree["m_Script"]["m_PathID"])
        if "shortname" in tree:
            tree["shortname"] = normalize_name(tree["shortname"])
            defs_by_path[obj.path_id] = tree
            short_by_go[go] = tree["shortname"]
        elif cls == "ItemBlueprint":
            bp_by_go[go] = tree
    items_af = next(o.assets_file for o in env.objects if o.assets_file)
    af_by_cab = {items_af.name: items_af}
    tree_by_short = {t["shortname"]: t for t in defs_by_path.values()}
    print(f"ItemDefinition: {len(defs_by_path)}, ItemBlueprint: {len(bp_by_go)}")

                                            
    env2 = UnityPy.load(content_path)
    type_configs = {}
    for obj in env2.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if isinstance(tree, dict) and "recyclerTypeConfigs" in tree:
            for cfg in tree["recyclerTypeConfigs"]:
                type_configs[int(cfg["recyclerType"])] = cfg
            break
    if not type_configs:
        sys.exit("RecyclerConfig not found in content bundle")

    rates = {}
    for rtype, cfg in type_configs.items():
        rate = RATE_BY_TYPE.get(rtype)
        if rate is None:
            print(f"  warn: unknown recyclerType {rtype}, skipping")
            continue
        rates[rate] = {"efficiency": round(float(cfg["efficiency"]), 4),
                       "duration": round(float(cfg["duration"]), 4)}
        if rate == "monument":
                                                           
            rates["monument_powered"] = {
                "efficiency": round(float(cfg["powergridEfficiency"]), 4),
                "duration": round(float(cfg["powergridDuration"]), 4),
                "efficiency_powergrid_stage": int(cfg["efficiencyBuffPowergridStage"]),
                "duration_powergrid_stage": int(cfg["durationBuffPowergridStage"]),
            }
        if cfg.get("requiredPowergridStageToUse"):
            rates[rate]["requires_powergrid_stage"] = int(cfg["requiredPowergridStageToUse"])
    print(f"recycler rates: {', '.join(f'{k} {int(v['efficiency'] * 100)}%' for k, v in rates.items())}")

                           
    def resolve_bp(sn, depth=0):
        if depth > 5:
            return None
        def_tree = tree_by_short.get(sn)
        if def_tree is None:
            return None
        bp = bp_by_go.get(def_tree["m_GameObject"]["m_PathID"])
        if bp is not None:
            return bp
        red = def_tree.get("isRedirectOf")
        if red and (red["m_PathID"] or red["m_FileID"]):
            base_sn = pptr_name(af_by_cab, defs_by_path, items_af, red)
            if base_sn and base_sn != sn:
                return resolve_bp(base_sn, depth + 1)
        return None

    items = {}
    stats = {"recyclable": 0, "empty": 0}
    for sn in sorted(tree_by_short):
        bp = resolve_bp(sn)
        scrap_base = float(bp["scrapFromRecycle"]) if bp else 0.0
        ingredients = []
        if bp:
            for ing in bp["ingredients"]:
                ing_sn = pptr_name(af_by_cab, defs_by_path, items_af, ing["itemDef"])
                if ing_sn and float(ing["amount"]) > 0:
                    ingredients.append((ing_sn, float(ing["amount"])))
                                                                                  
        make = [(s, a) for s, a in ingredients if s != "scrap"]
        if not make and scrap_base <= 0:
            items[sn] = {"recyclable": False}
            stats["empty"] += 1
            continue
        atc = int(bp["amountToCreate"]) or 1
        outputs = {}
        scrap = {}
        for rate, cfg in rates.items():
            eff = cfg["efficiency"]
            entries = []
            for ing_sn, amount in make:
                x = amount * eff / atc
                whole = int(x)
                chance = round(x - whole, 4)
                entry = {"item": ing_sn, "amount": whole}
                if chance > 1e-9:
                    entry["chance"] = min(chance, 0.9999)
                entries.append(entry)
            outputs[rate] = entries
            if scrap_base > 0:
                scrap[rate] = round_val(scrap_base * 2 * eff)
        rec = {"recyclable": True, "scrap": scrap or None, "outputs": outputs}
        items[sn] = rec
        stats["recyclable"] += 1

    result = {"recyclers": rates, "items": items}
    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nDone: {stats['recyclable']} recyclable, {stats['empty']} not -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
