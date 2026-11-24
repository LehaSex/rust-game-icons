"""Build gate: has Rust shipped a build this repository has not parsed?

Polls SteamCMD's public app-info endpoint for app 252490 and compares the
public branch buildid with the buildid recorded in manifest.json.
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

DEFAULT_URL = "https://api.steamcmd.net/v1/info/252490"
APP_ID = "252490"
DEFAULT_BRANCH = "public"
ENV_BRANCH = "STEAM_BRANCH"
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


def fetch_info(url: str, timeout: int) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "rust-icons-pipeline/1", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise VersionError(f"{url} -> HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VersionError(f"{url} unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VersionError(f"{url} returned malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise VersionError(f"{url} returned {type(payload).__name__}, expected an object")
    return payload


def extract_buildid(payload: dict, branch: str) -> int:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise VersionError("no data block in the SteamCMD response")

    app = data.get(APP_ID)
    if not isinstance(app, dict):
        raise VersionError(f"no data.{APP_ID} block in the SteamCMD response")

    depots = app.get("depots")
    if not isinstance(depots, dict):
        raise VersionError(f"no data.{APP_ID}.depots block in the SteamCMD response")

    branches = depots.get("branches")
    if not isinstance(branches, dict):
        raise VersionError(f"no data.{APP_ID}.depots.branches block in the SteamCMD response")

    node = branches.get(branch)
    if not isinstance(node, dict):
        raise VersionError(f"no data.{APP_ID}.depots.branches.{branch} block in the SteamCMD response")

    raw = node.get("buildid")
    if raw is None:
        raise VersionError(f"data.{APP_ID}.depots.branches.{branch}.buildid is missing")

    try:
        buildid = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise VersionError(f"buildid is {raw!r}, expected an integer") from exc
    if buildid <= 0:
        raise VersionError(f"buildid is {buildid!r}, expected a positive integer")
    return buildid


def fetch_buildid(url: str, branch: str, timeout: int) -> int:
    return extract_buildid(fetch_info(url, timeout), branch)


def read_local(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VersionError(f"{path} is not an object")
    buildid = data.get("buildid")
    if buildid is None:
        return None
    if not isinstance(buildid, int) or isinstance(buildid, bool):
        try:
            buildid = int(str(buildid).strip())
        except (TypeError, ValueError) as exc:
            raise VersionError(
                f"{path}: buildid is {buildid!r}, expected an integer"
            ) from exc
    if buildid <= 0:
        raise VersionError(f"{path}: buildid is {buildid!r}, expected a positive integer")
    return buildid


def main() -> int:
    ap = argparse.ArgumentParser(description="Build gate")
    ap.add_argument("--url", default=DEFAULT_URL,
                    help=f"SteamCMD app-info endpoint (default {DEFAULT_URL})")
    ap.add_argument("--branch", default=os.environ.get(ENV_BRANCH, DEFAULT_BRANCH),
                    help=f"Steam branch to poll (default {DEFAULT_BRANCH})")
    ap.add_argument("--local", type=Path, default=REPO / "manifest.json",
                    help="build file inside the repository (default <repo>/manifest.json)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="seconds to wait for the app-info response")
    ap.add_argument("--force", action="store_true", help="always run")
    ap.add_argument("--on-error", choices=("skip", "patch-day"), default="skip",
                    help="what to decide when the build cannot be read (default skip)")
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
    print(f"app info  : {args.url}")
    print(f"branch    : {args.branch}")

    remote = local = None
    mode = "forced" if forced else "build"
    error = ""

    try:
        remote = fetch_buildid(args.url, args.branch, args.timeout)
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
                out.set("reason", f"build unreadable: {error}")
                out.set("local_buildid", local if local is not None else "")
                out.set("remote_buildid", "")
                out.flush()
                return 0

    if mode == "patch-day":
        run, reason = is_patch_day.evaluate(now, args.weekday, args.max_day)
        reason = f"{reason} (build unreadable: {error})"
    elif mode == "forced":
        run = True
        reason = "forced" if remote is None else f"forced (Steam buildid is {remote})"
    elif local is None:
        run, reason = True, f"no buildid recorded in {args.local.name}; taking a first reading"
    elif remote > local:
        run, reason = True, f"Steam buildid is {remote}, repository has {local}"
    elif remote == local:
        run, reason = False, f"Steam buildid is still {remote}; nothing to do"
    else:
        run, reason = False, (f"Steam buildid is {remote}, repository has {local} "
                              f"-- the Steam build is behind the repository?")

    print(f"recorded  : {local if local is not None else 'none'}")
    print(f"live build: {remote if remote is not None else 'unknown'}")
    print(f"gate      : {mode} -> {'run' if run else 'skip'}")
    print(f"reason    : {reason}")

    out.set("should_run", "true" if run else "false")
    out.set("reason", reason)
    out.set("local_buildid", local if local is not None else "")
    out.set("remote_buildid", remote if remote is not None else "")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
