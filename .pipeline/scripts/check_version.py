"""Version gate: has Rust shipped a build this repository has not parsed?

Polls the game's own manifest endpoint, which the game itself hits every hour to
decide whether a connecting client is too old, and compares Changesets.Main with
the version recorded in manifest.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import is_patch_day  # noqa: E402

DEFAULT_URL = "https://api.facepunch.com/api/public/manifest/"
ENV_KEY = "FACEPUNCH_PUBLIC_KEY"
ENV_FORCE = "VERSION_FORCE"
DEFAULT_TIMEOUT = 30


class VersionError(RuntimeError):
    pass


class Outputs:
    def __init__(self) -> None:
        self._path = os.environ.get("GITHUB_OUTPUT", os.devnull)
        self._lines: list[str] = []

    def set(self, name: str, value: object) -> None:
        self._lines.append(f"{name}={value}")

    def flush(self) -> None:
        for line in self._lines:
            print(line)
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(self._lines) + "\n")
        except OSError:
            pass


def _redacted(target: str, key: str) -> str:
    return target.split("?", 1)[0] if key else target


def fetch_manifest(url: str, key: str, timeout: int) -> dict:
    if not key:
        raise VersionError(f"{ENV_KEY} is empty; the manifest endpoint needs a public_key")

    target = f"{url.rstrip('/')}/?public_key={key}"
    pretty = _redacted(target, key)
    request = urllib.request.Request(
        target, headers={"User-Agent": "rust-icons-pipeline/1", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise VersionError(f"{pretty} -> HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VersionError(f"{pretty} unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VersionError(f"{pretty} returned malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise VersionError(f"{pretty} returned {type(payload).__name__}, expected an object")
    return payload


def fetch_changesets(url: str, key: str, timeout: int) -> dict:
    payload = fetch_manifest(url, key, timeout)
    changesets = payload.get("Changesets")
    if not isinstance(changesets, dict):
        raise VersionError("no Changesets block in the manifest")

    main = changesets.get("Main")
    if not isinstance(main, int) or isinstance(main, bool):
        raise VersionError(f"Changesets.Main is {main!r}, expected an integer")
    return changesets


def read_local(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VersionError(f"{path} is not an object")
    version = data.get("version")
    if version is None:
        return None
    if not isinstance(version, int) or isinstance(version, bool):
        raise VersionError(f"{path}: version is {version!r}, expected an integer")
    return version


def main() -> int:
    ap = argparse.ArgumentParser(description="Version gate")
    ap.add_argument("--url", default=DEFAULT_URL,
                    help=f"manifest endpoint (default {DEFAULT_URL})")
    ap.add_argument("--key", default=os.environ.get(ENV_KEY, ""),
                    help=f"manifest public_key (${ENV_KEY})")
    ap.add_argument("--local", type=Path, default=REPO / "manifest.json",
                    help="version file inside the repository (default <repo>/manifest.json)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="seconds to wait for the manifest")
    ap.add_argument("--force", action="store_true", help="always run")
    ap.add_argument("--on-error", choices=("skip", "patch-day"), default="skip",
                    help="what to decide when the manifest cannot be read (default skip)")
    ap.add_argument("--weekday", type=int,
                    default=is_patch_day.env_int(is_patch_day.ENV_TIME, 2),
                    help="fallback patch day, cron numbering (default 2, Tuesday)")
    ap.add_argument("--max-day", type=int,
                    default=is_patch_day.env_int(is_patch_day.ENV_MAX_DAY, 7),
                    help="fallback window: largest day of the month to consider (default 7)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    forced = args.force or os.environ.get(ENV_FORCE) == "1"
    out = Outputs()

    print(f"utc now   : {now:%Y-%m-%d %H:%M:%S %Z}")
    print(f"manifest  : {args.url}")

    remote = local = staging = None
    mode = "forced" if forced else "version"
    error = ""

    try:
        changesets = fetch_changesets(args.url, args.key, args.timeout)
        remote = changesets.get("Main")
        staging = changesets.get("Staging")
        local = read_local(args.local)
    except VersionError as exc:
        error = str(exc)
        sys.stdout.flush()
        print(f"warning: {error}", file=sys.stderr)
        if not forced:
            if args.on_error == "patch-day":
                mode = "patch-day"
            else:
                out.set("should_run", "false")
                out.set("reason", f"manifest unreadable: {error}")
                out.set("local_version", local if local is not None else "")
                out.set("remote_version", "")
                out.flush()
                return 0

    if mode == "patch-day":
        run, reason = is_patch_day.evaluate(now, args.weekday, args.max_day)
        reason = f"{reason} (manifest unreadable: {error})"
    elif mode == "forced":
        run = True
        reason = "forced" if remote is None else f"forced (Changesets.Main is {remote})"
    elif local is None:
        run, reason = True, f"no version recorded in {args.local.name}; taking a first reading"
    elif remote > local:
        run, reason = True, f"Changesets.Main is {remote}, repository has {local}"
    elif remote == local:
        run, reason = False, f"Changesets.Main is still {remote}; nothing to do"
    else:
        run, reason = False, (f"Changesets.Main is {remote}, repository has {local} "
                              f"-- the remote is behind the repository?")

    print(f"recorded  : {local if local is not None else 'none'}")
    print(f"live main : {remote if remote is not None else 'unknown'}")
    print(f"gate      : {mode} -> {'run' if run else 'skip'}")
    print(f"reason    : {reason}")

    out.set("should_run", "true" if run else "false")
    out.set("reason", reason)
    out.set("local_version", local if local is not None else "")
    out.set("remote_version", remote if remote is not None else "")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
