                      

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
DEFAULT_OUT = SCRIPT_DIR.parent / "items.craft.json"

RARITY_NAMES = ["None", "Common", "Uncommon", "Rare", "VeryRare"]
                                                                                                           
RESEARCH_SCRAP_BY_RARITY = {0: 120, 1: 15, 2: 30, 3: 60, 4: 120}
                                                             
DEFAULT_BLUEPRINT_RESEARCH_SCRAP = 10

                                                                                          
TIME_CAPPED_CATEGORIES = {1, 9}

                                                                     
                                                            
DESPAWN_SECONDS_BY_TIER = {0: 300, 1: 300, 2: 1200, 3: 2400, 4: 3600}
                                                                       
QUICK_DESPAWN_SECONDS = 30

                                                                                            
                                                         
                                                                      
NORMAL_TREES = {"TechTreeT0": "workbench1", "TechTreeT2": "workbench2", "TechTreeT3": "workbench3"}
                                                                                          
                                                                                                
ENGINEERING_TREE = "TechTreeIO"
                                                                                       
WORKBENCH_ORDER = {"workbench1": 1, "workbench2": 2, "workbench3": 3, "iotable": 9}
                                                                          
                                                                               
CRAFT_WORKBENCH_BY_LEVEL = {1: "workbench1", 2: "workbench2", 3: "workbench3", 4: "workbench4"}

                                                                                 
                                                                       
FIELD_DEFAULTS = {
    "craftable": False,
    "craft_workbench": None,
    "amount": 0,
    "time": 0,
    "ingredients": [],
    "rarity": None,
    "researchable": False,
    "research_scrap": None,
    "default_blueprint": False,
    "scrap_from_recycle": 0,
    "research_workbench": None,
    "techtree_scrap": None,
    "needs_steam_item": False,
    "require_unlocked_item": None,
    "additional_unlocks": [],
    "force_time": False,
    "skin_of": None,
    "stack_size": 0,
    "despawn": 0,
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Rust item crafting data to items.craft.json.")
    parser.add_argument("--game-dir", default=None,
                        help=f"Rust install root ({ENV_GAME_DIR})")
    parser.add_argument("--items-bundle", default=None,
                        help=f"items.preload.bundle (env {ENV_ITEMS_BUNDLE} or --game-dir)")
    parser.add_argument("--content-bundle", default=None,
                        help=f"content.bundle (env {ENV_CONTENT_BUNDLE} or --game-dir)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output json path")
    args = parser.parse_args()

    items_path = require_file(items_bundle(args.items_bundle, args.game_dir), "items.preload.bundle")
    content_path = require_file(content_bundle(args.content_bundle, args.game_dir), "content.bundle")

                                                           
    env = UnityPy.load(str(items_path))
    defs_by_path = {}
    def_by_go = {}
    short_by_go = {}
    bp_by_go = {}
    go_mods = {}
    redirects = []
    scripts_by_path = {}
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            scripts_by_path[obj.path_id] = obj.read().m_ClassName
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        af = obj.assets_file
        data = obj.read()
        tree = obj.read_typetree()
        if not isinstance(tree, dict):
            continue
        go = data.m_GameObject.m_PathID
        cls = scripts_by_path.get(data.m_Script.m_PathID)
        if cls and (cls.startswith("ItemMod") or cls.startswith("Item")):
            go_mods.setdefault(go, set()).add(cls)
        if "shortname" in tree:
            tree["shortname"] = normalize_name(tree["shortname"])
            defs_by_path[obj.path_id] = tree
            def_by_go[go] = tree
            short_by_go[go] = tree["shortname"]
            red = tree.get("isRedirectOf")
            if red and (red["m_PathID"] or red["m_FileID"]):
                redirects.append((tree, red, af))
        elif "ingredients" in tree:
            bp_by_go[go] = tree
    items_af = next(o.assets_file for o in env.objects if o.assets_file)
    items_cab = items_af.name
    print(f"ItemDefinition: {len(defs_by_path)}, ItemBlueprint: {len(bp_by_go)}, redirects: {len(redirects)}")

    af_by_cab = {items_cab: items_af}

    def def_rarity_sn(sn, depth=0):
        if depth > 5 or sn is None:
            return 4
        t = next((t for t in defs_by_path.values() if t["shortname"] == sn), None)
        if t is None:
            return 4
        red = t.get("isRedirectOf")
        if red and (red["m_PathID"] or red["m_FileID"]):
            base = pptr_name(af_by_cab, defs_by_path, items_af, red)
            if base and base != sn:
                return def_rarity_sn(base, depth + 1)
        return int(t["rarity"])

    def scrap_for_research(sn):
        return RESEARCH_SCRAP_BY_RARITY.get(def_rarity_sn(sn), 120)

                                                
    env2 = UnityPy.load(str(content_path))
    techtree_tier = {}
    techtree_scrap = {}
    for obj in env2.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        af = obj.assets_file
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict) or "techTreeLevel" not in tree or "nodes" not in tree:
            continue
        tier = NORMAL_TREES.get(tree["m_Name"])
        is_engineering = tree["m_Name"] == ENGINEERING_TREE
        if tier is None and not is_engineering:
            continue
        by_id = {}
        for node in tree["nodes"]:
            sn = pptr_name(af_by_cab, defs_by_path, af, node["itemDef"])
            by_id[node["id"]] = {"sn": sn, "inputs": node["inputs"], "group": node["groupName"]}
        entry_id = next((nid for nid, n in by_id.items() if n["group"] == "Entry"), None)
        memo = {}

        def full_cost(nid, stack):
            if nid in memo:
                return memo[nid]
            if nid in stack:
                print(f"  warn: cycle in tree {tree['m_Name']} at node {nid}")
                return 0
            n = by_id[nid]
            own = scrap_for_research(n["sn"]) if n["sn"] else 0
            inputs = [i for i in n["inputs"] if i in by_id]
            if nid == entry_id:
                v = 0
            elif not inputs:
                v = own
            else:
                v = own + min(full_cost(i, stack | {nid}) for i in inputs)
            memo[nid] = v
            return v

        for nid, n in by_id.items():
            if n["sn"] is None:
                continue
            level = "iotable" if is_engineering else tier
            prev = techtree_tier.get(n["sn"])
                                                                                               
            if (prev is None or level == "iotable"
                    or (prev != "iotable" and WORKBENCH_ORDER[level] < WORKBENCH_ORDER[prev])):
                techtree_tier[n["sn"]] = level
                techtree_scrap[n["sn"]] = full_cost(nid, frozenset())

                           
    result = {}
    stats = {"bp": 0, "no_ing_resolve": 0, "redirect_only": 0, "both": 0}

                                                                           
    def is_holdable(go):
        return "ItemModEntity" in go_mods.get(go, set())

    def is_wearable(go):
        return "ItemModWearable" in go_mods.get(go, set())

    def is_usable(go):
        mods = go_mods.get(go, set())
        return bool({"ItemModEntity", "ItemModConsume", "ItemModConsumable"} & mods)

    def effective_craft_time(bp, go, def_tree):
        time_raw = float(bp["time"])
        if bp["ForceThisCraftTime"]:
            return time_raw
        capped = (def_tree["stackable"] == 1 or is_holdable(go) or is_wearable(go)
                  or is_usable(go) or def_tree["category"] in TIME_CAPPED_CATEGORIES)
        if capped:
            cap = 5 + max(bp["workbenchLevelRequired"], 1) * 10
            return min(cap, time_raw)
        return time_raw

    for go, bp in bp_by_go.items():
        target = short_by_go.get(go)
        if target is None:
            print(f"  warn: blueprint without ItemDefinition on GO {go}")
            continue
        def_tree = def_by_go[go]
        rec = {}
        rec["craftable"] = bool(bp["userCraftable"])
        rec["craft_workbench"] = CRAFT_WORKBENCH_BY_LEVEL.get(int(bp["workbenchLevelRequired"]))
        rec["amount"] = int(bp["amountToCreate"])
        rec["time"] = round(effective_craft_time(bp, go, def_tree), 2)
        ingredients = []
        for ing in bp["ingredients"]:
            sn = pptr_name(af_by_cab, defs_by_path, items_af, ing["itemDef"])
            if sn is None:
                stats["no_ing_resolve"] += 1
                continue
            ingredients.append({"item": sn, "amount": int(ing["amount"])})
        rec["ingredients"] = ingredients
        rarity = int(def_tree["rarity"])
        rec["rarity"] = RARITY_NAMES[rarity]
        if bp["isResearchable"]:
            rec["researchable"] = True
            rec["research_scrap"] = (DEFAULT_BLUEPRINT_RESEARCH_SCRAP if bp["defaultBlueprint"]
                                     else RESEARCH_SCRAP_BY_RARITY.get(rarity, 120))
        else:
            rec["researchable"] = False
        if bp["defaultBlueprint"]:
            rec["default_blueprint"] = True
        if bp["scrapFromRecycle"]:
            rec["scrap_from_recycle"] = int(bp["scrapFromRecycle"])
        tier = techtree_tier.get(target)
        if tier is not None:
            rec["research_workbench"] = tier
            rec["techtree_scrap"] = techtree_scrap[target]
        if bp["NeedsSteamItem"]:
            rec["needs_steam_item"] = True
        ru = bp["RequireUnlockedItem"]
        if ru and (ru["m_PathID"] or ru["m_FileID"]):
            sn = pptr_name(af_by_cab, defs_by_path, items_af, ru)
            if sn:
                rec["require_unlocked_item"] = sn
        if bp["additionalUnlocks"]:
            extra = []
            for pptr in bp["additionalUnlocks"]:
                sn = pptr_name(af_by_cab, defs_by_path, items_af, pptr)
                if sn:
                    extra.append(sn)
            if extra:
                rec["additional_unlocks"] = extra
        if bp["ForceThisCraftTime"]:
            rec["force_time"] = True
        result[target] = rec
        stats["bp"] += 1

                                                          
    for def_tree, red, src_af in redirects:
        base = pptr_name(af_by_cab, defs_by_path, src_af, red)
        if base is None:
            print(f"  warn: unresolved redirect for {def_tree['shortname']}")
            continue
        sn = def_tree["shortname"]
        if sn in result:
            result[sn]["skin_of"] = base
            stats["both"] += 1
        else:
            result[sn] = {"skin_of": base}
            stats["redirect_only"] += 1

                                                     
    if len({t["shortname"] for t in defs_by_path.values()}) != len(defs_by_path):
        print("  warn: shortname collision after legacy name normalization")
    tree_by_short = {t["shortname"]: t for t in defs_by_path.values()}
    red_sn_by_short = {}
    for def_tree, red, src_af in redirects:
        sn = pptr_name(af_by_cab, defs_by_path, src_af, red)
        if sn:
            red_sn_by_short[def_tree["shortname"]] = sn

    def despawn_seconds(def_tree, depth=0):
        if depth > 5:
            return DESPAWN_SECONDS_BY_TIER[0]
        if int(def_tree.get("quickDespawn") or 0):
            return QUICK_DESPAWN_SECONDS
        tier = int(def_tree.get("despawnRarity") or 0)
        if tier == 0:
            base = tree_by_short.get(red_sn_by_short.get(def_tree["shortname"]))
            if base is not None and base is not def_tree:
                return despawn_seconds(base, depth + 1)
            tier = int(def_tree.get("rarity") or 0)
        return DESPAWN_SECONDS_BY_TIER.get(tier, DESPAWN_SECONDS_BY_TIER[0])

    for def_tree in defs_by_path.values():
        rec = result.setdefault(def_tree["shortname"], {})
        for field, default in FIELD_DEFAULTS.items():
            if field not in rec:
                rec[field] = list(default) if isinstance(default, list) else default
        rec["rarity"] = RARITY_NAMES[int(def_tree["rarity"])]
        rec["stack_size"] = int(def_tree.get("stackable") or 0)
        rec["despawn"] = despawn_seconds(def_tree)
    keysets = {frozenset(r) for r in result.values()}
    if len(keysets) != 1:
        print(f"  warn: contract mismatch, {len(keysets)} key sets")
    result = {k: {f: r[f] for f in FIELD_DEFAULTS} for k, r in result.items()}

                                                    
    items_json = SCRIPT_DIR.parent / "items.json"
    if items_json.is_file():
        repo = json.loads(items_json.read_text(encoding="utf-8"))
        repo_names = {i["image_name"] for i in repo}
        extra = sorted(set(result) - repo_names)
        missing = sorted(repo_names - set(result))
        print(f"not in repo items.json ({len(extra)}): {extra[:10]}{'...' if len(extra) > 10 else ''}")
        print(f"in repo but no craft data ({len(missing)}), e.g.: {missing[:10]}")

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nDone: {len(result)} items -> {out}")
    print(f"stats: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
