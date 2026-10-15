
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:
    sys.exit("UnityPy is not installed: pip install UnityPy")

LOC_RE = re.compile(r"^assets/localization/([^/]+)/([^/]+\.json)$")
WANT = ("ItemDefinition", "ItemBlueprint", "TechTreeData")


def probe(path: Path, deep: bool) -> None:
    print("=" * 70)
    print(path.name, f"({path.stat().st_size / 2**30:.2f} GiB)")
    env = UnityPy.load(str(path))

                                                                     
    langs: dict[str, int] = {}
    for key in env.container:
        m = LOC_RE.match(key)
        if m:
            langs[m.group(1)] = langs.get(m.group(1), 0) + 1
    print(f"  localization: {len(langs)} languages")
    if langs:
        top = sorted(langs.items(), key=lambda x: -x[1])[:5]
        print(f"    {top}")

                                                          
    counts: dict[str, int] = {}
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            name = obj.read().m_ClassName
            counts[name] = counts.get(name, 0) + 1
    print(f"  classes: {len(counts)}")
    for w in WANT:
        print(f"    {w}: {counts.get(w, 0)}")

    if not deep:
        print("  (--deep not set, typetrees were not read)")
        return

    found = None
    scanned = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        scanned += 1
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if "recyclerTypeConfigs" in tree:
            found = tree
            break
    if found:
        print(f"  RecyclerConfig: FOUND (object {scanned})")
        cfgs = found["recyclerTypeConfigs"]
        for c in cfgs[:4]:
            print(f"    type={c.get('recyclerType')} eff={c.get('efficiency')} "
                  f"dur={c.get('duration')}")
    else:
        print(f"  RecyclerConfig: NOT FOUND (read {scanned} MonoBehaviour)")


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="What is inside the game bundles")
    ap.add_argument("bundles", nargs="+", type=Path)
    ap.add_argument("--deep", action="store_true",
                    help="read typetrees (slow, but looks for RecyclerConfig)")
    args = ap.parse_args()

    for b in args.bundles:
        if not b.is_file():
            print(f"file not found: {b}")
            continue
        probe(b, args.deep)
    return 0


if __name__ == "__main__":
    sys.exit(main())