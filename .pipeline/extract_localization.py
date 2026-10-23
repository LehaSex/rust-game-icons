import argparse
import json
import re
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:
    sys.exit("UnityPy is not installed. Run: pip install UnityPy")

from paths import ENV_CONTENT_BUNDLE, ENV_GAME_DIR, content_bundle, require_file

KEY_RE = re.compile(r"^assets/localization/([^/]+)/([^/]+\.json)$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Rust localization files from the game bundle.")
    parser.add_argument("--game-dir", default=None,
                        help=f"Rust install root ({ENV_GAME_DIR})")
    parser.add_argument("--bundle", default=None,
                        help=f"content.bundle (env {ENV_CONTENT_BUNDLE} or --game-dir)")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "localization"),
                        help="output directory (default: automation/localization)")
    args = parser.parse_args()

    bundle_path = require_file(content_bundle(args.bundle, args.game_dir), "content.bundle")
    out_dir = Path(args.out)

    env = UnityPy.load(str(bundle_path))
    extracted = 0
    for key, obj in env.container.items():
        m = KEY_RE.match(key)
        if not m:
            continue
        lang, name = m.groups()
        data = obj.read()
        raw = data.m_Script
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "surrogateescape")
        json.loads(raw)
        dest = out_dir / lang
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_bytes(raw)
        extracted += 1
        print(f"{lang}/{name}  {len(raw):,} bytes")

    print(f"\nDone: {extracted} files -> {out_dir}")
    return 0 if extracted else 1


if __name__ == "__main__":
    sys.exit(main())
