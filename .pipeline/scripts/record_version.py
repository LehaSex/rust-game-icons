"""Stamp the processed build into manifest.json.

Called twice per run: right after the gate (staged only, so open_pr.py commits it
with the data) and again with --push when nothing else was published.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_version  # noqa: E402

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "actions@users.noreply.github.com"


def optional_int(raw: str) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw else None


def git(args: list[str], repo: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print("$", " ".join(args[:2]), "…")
    if check and proc.returncode != 0:
        sys.exit(f"git failed: {proc.stderr[-500:]}")
    return proc


def write_version(path: Path, version: int, when: str) -> bool:
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            data = loaded

    previous = data.get("version")
    if previous == version:
        print(f"{path.name} already records version {version}")
        return False

    data["version"] = version
    data["updated_at"] = when
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{path.name}: {previous if previous is not None else 'none'} -> {version} ({when})")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Stamp the processed build into manifest.json")
    ap.add_argument("--version", type=optional_int, default=None,
                    help="build number to record; fetched from the manifest when omitted or empty")
    ap.add_argument("--url", default=check_version.DEFAULT_URL,
                    help="manifest endpoint, used only when --version is omitted")
    ap.add_argument("--key", default=os.environ.get(check_version.ENV_KEY, ""),
                    help=f"manifest public_key (${check_version.ENV_KEY})")
    ap.add_argument("--timeout", type=int, default=check_version.DEFAULT_TIMEOUT)
    ap.add_argument("--local", type=Path, default=None,
                    help="version file inside the repository (default <repo>/manifest.json)")
    ap.add_argument("--repo", type=Path, default=REPO, help="git repository root")
    ap.add_argument("--date", default=None, help="timestamp to store, ISO 8601 (default: now, UTC)")
    ap.add_argument("--push", action="store_true",
                    help="commit and push; without this the file is only staged")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    version = args.version
    if version is None:
        try:
            version = check_version.fetch_changesets(args.url, args.key, args.timeout)["Main"]
        except check_version.VersionError as exc:
            sys.exit(f"cannot determine the live build: {exc}")
    if version <= 0:
        sys.exit(f"refusing to record version {version}")

    when = args.date or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    repo = args.repo.resolve()
    local = (args.local or repo / "manifest.json").resolve()
    if not (repo / ".git").is_dir():
        sys.exit(f"{repo} is not a git repository")
    try:
        rel = local.relative_to(repo).as_posix()
    except ValueError:
        sys.exit(f"{local} is outside {repo}; git cannot stage it from this repo")

    write_version(local, version, when)

    git(["git", "add", "--", rel], repo)
    if rel not in git(["git", "diff", "--cached", "--name-only"], repo).stdout.split():
        print("nothing to commit")
        return 0
    if not args.push:
        print(f"staged {rel}; the publish step will commit it")
        return 0

    git(["git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-m", f"chore: game version {version}",
         "-m", f"Changesets.Main is now {version}, recorded so the next hourly poll "
               f"has a baseline."], repo)

    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    data_repo = os.environ.get("DATA_REPO", "")
    if not token or not data_repo:
        print("no GH_PAT or DATA_REPO - the commit is local, push it by hand")
        return 0

    branch = os.environ.get("VERSION_BRANCH", "main")
    git(["git", "remote", "set-url", "origin",
         f"https://x-access-token:{token}@github.com/{data_repo}.git"], repo, check=False)
    git(["git", "push", "origin", f"HEAD:{branch}"], repo)
    print(f"pushed {version} to {data_repo}:{branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
