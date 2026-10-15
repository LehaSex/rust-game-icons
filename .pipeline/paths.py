
from __future__ import annotations

import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent

ENV_GAME_DIR = "RUST_GAME_DIR"
ENV_ITEMS_BUNDLE = "RUST_ITEMS_BUNDLE"
ENV_CONTENT_BUNDLE = "RUST_CONTENT_BUNDLE"
ENV_ITEMS_DIR = "RUST_ITEMS_DIR"


def _env(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else None


def game_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    found = _env(ENV_GAME_DIR)
    if found:
        return found
    raise SystemExit(
        f"No game path given. Set {ENV_GAME_DIR} or pass --game-dir.\n"
        "Example: set RUST_GAME_DIR=E:\\SteamLibrary\\steamapps\\common\\Rust"
    )


def bundles_dir(explicit: str | None = None) -> Path:
    return game_dir(explicit) / "Bundles" / "shared"


def items_bundle(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    found = _env(ENV_ITEMS_BUNDLE)
    if found:
        return found
    return bundles_dir() / "items.preload.bundle"


def content_bundle(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    found = _env(ENV_CONTENT_BUNDLE)
    if found:
        return found
    return bundles_dir() / "content.bundle"


def items_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    found = _env(ENV_ITEMS_DIR)
    if found:
        return found
    return game_dir() / "Bundles" / "items"


def resolve_items_dir(items: str | None = None, game: str | None = None) -> Path:
    """Items folder from an explicit --items-dir, else Bundles/items under the game root.

    Prefer this over items_dir(): callers hold a game root, not an items folder,
    and handing the wrong one to items_dir() silently yields the game root itself.
    """
    if items:
        return Path(items)
    return game_dir(game) / "Bundles" / "items"


def upscayl_bin() -> Path | None:
    raw = os.environ.get("UPSCAYL_BIN", "").strip()
    return Path(raw) if raw else None


def upscayl_models() -> Path | None:
    raw = os.environ.get("RUST_ITEMS_PRELOAD_DIR", "").strip()
    return Path(raw) if raw else None


def require_file(path: Path, what: str) -> Path:
    if not path.exists():
        raise SystemExit(
            f"{what} not found: {path}\n"
            f"Set the environment variable or pass the path as an argument."
        )
    return path


def add_common_args(parser, *, game: bool = True, items_dir_arg: bool = False) -> None:
    if game:
        parser.add_argument("--game-dir", default=None, help=f"Rust install root ({ENV_GAME_DIR})")
    if items_dir_arg:
        parser.add_argument("--items-dir", default=None, help=f"Bundles/items folder ({ENV_ITEMS_DIR})")