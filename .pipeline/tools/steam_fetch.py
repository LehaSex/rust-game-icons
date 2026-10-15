"""Fetch game depots from SteamPipe, authenticating with a maFile.

Drives SteamRE/DepotDownloader (the .NET tool) and feeds it the Steam Guard
code generated from a maFile, so a 2FA-protected account can be logged in
without a phone and without a password ever reaching the command line.

Safety rules:

* the password is read from the environment and written to the child's stdin,
  never to argv (argv is world-readable via `ps` on Linux);
* the maFile is decoded in memory and never touches disk here;
* generated codes are redacted from the tool's output before it is printed;
* refuses to authenticate in a pull_request context, where the code being run
  may come from a fork and therefore from someone you do not control.

Anonymous downloads (the Rust dedicated server, AppID 258550) need none of
this and are the default when no credentials are configured.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))

import steam_guard
from steam_guard import GuardError

ENV_USER = "STEAM_USERNAME"
ENV_PASS = "STEAM_PASSWORD"
ENV_TOOL = "DEPOTDOWNLOADER"

TOOL_NAMES = ("DepotDownloader", "DepotDownloader.exe")

RUST_CLIENT_APP = 252490
RUST_CLIENT_DEPOT = 252494
RUST_SERVER_APP = 258550

UNTRUSTED_EVENTS = {"pull_request", "pull_request_target"}
WORKFLOWS = ("GITHUB_ACTIONS", "GITHUB_WORKFLOW")


def die(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def untrusted_context() -> str:
    """Name the event when the code being run may come from a fork."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event in UNTRUSTED_EVENTS:
        return event
    head = os.environ.get("GITHUB_HEAD_REPOSITORY", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if head and repo and head != repo:
        return f"{event or 'workflow'} from fork {head}"
    return ""


def find_tool(explicit: str | None) -> Path:
    if explicit or os.environ.get(ENV_TOOL):
        path = Path(explicit or os.environ[ENV_TOOL]).expanduser()
        if not path.is_file():
            die(f"{ENV_TOOL} points at a file that does not exist: {path}")
        return path
    for name in TOOL_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    die(
        "DepotDownloader not found on PATH. Download it from\n"
        "  https://github.com/SteamRE/DepotDownloader/releases/latest\n"
        f"then either put it on PATH or set {ENV_TOOL}."
    )


def build_argv(tool: Path, args: argparse.Namespace, username: str | None) -> list[str]:
    app = args.app
    if app is None:
        app = RUST_SERVER_APP if args.anonymous else RUST_CLIENT_APP

    cmd = [str(tool), "-app", str(app), "-dir", str(args.dest)]

    if username:
        cmd += ["-username", username]
        cmd += ["-no-mobile", "-loginid", str(args.loginid)]
    elif not args.anonymous:
        die("no --username and no --anonymous; refusing to guess the account")

    if args.depot:
        cmd += ["-depot", str(args.depot)]
    if args.branch:
        cmd += ["-branch", args.branch]
    if args.filelist:
        if not Path(args.filelist).is_file():
            die(f"filelist not found: {args.filelist}")
        cmd += ["-filelist", str(args.filelist)]
    if args.manifest_only:
        cmd.append("-manifest-only")
    if args.os:
        cmd += ["-os", args.os]
    if args.validate:
        cmd.append("-validate")
    if args.max_downloads:
        cmd += ["-max-downloads", str(args.max_downloads)]
    if args.debug:
        cmd.append("-debug")
    return cmd


def stdin_payload(password: str, guard_codes: list[str]) -> str:
    """DepotDownloader reads the password, then the 2FA code, from the same stdin.

    Codes for several consecutive windows are queued so a rejected first code
    does not need another process.
    """
    lines = [password, *guard_codes]
    return "\n".join(lines) + "\n"


def run(cmd: list[str], payload: str, secrets: tuple[str, ...]) -> int:
    print("$ " + " ".join(cmd), flush=True)
    print(f"  (auth: stdin, {len(payload.splitlines())} line(s) withheld)", flush=True)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdin is not None
    try:
        proc.stdin.write(payload)
        proc.stdin.close()
    except BrokenPipeError:
        pass

    assert proc.stdout is not None
    for line in proc.stdout:
        print("  " + steam_guard.redact(line.rstrip("\n"), secrets), flush=True)

    return proc.wait()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Download Steam depots, with optional maFile Steam Guard auth"
    )
    ap.add_argument("--app", type=int, default=None,
                    help=f"AppID (default: {RUST_CLIENT_APP}, or {RUST_SERVER_APP} with --anonymous)")
    ap.add_argument("--depot", type=int, default=None, help="DepotID")
    ap.add_argument("--branch", default=None, help="branch name (default: public)")
    ap.add_argument("--dest", type=Path, default=Path("game-assets"), help="download directory")
    ap.add_argument("--filelist", default=None, help="file list; see make_filelist.py")
    ap.add_argument("--manifest-only", action="store_true", help="write a manifest, download nothing")
    ap.add_argument("--validate", action="store_true", help="checksum files already on disk")
    ap.add_argument("--os", default=None, choices=("windows", "linux", "macos"),
                    help="platform depot to pull (default: host OS)")
    ap.add_argument("--max-downloads", type=int, default=None)
    ap.add_argument("--debug", action="store_true")

    ap.add_argument("--anonymous", action="store_true",
                    help=f"no login at all; required for the {RUST_SERVER_APP} dedicated server")
    ap.add_argument("--username", default=None, help=f"defaults to ${ENV_USER}")
    ap.add_argument("--maFile", default=None, help=f"path to a maFile outside the repo; "
                                                  f"defaults to ${steam_guard.ENV_PATH} or ${steam_guard.ENV_B64}")
    ap.add_argument("--tool", default=None, help=f"path to DepotDownloader; defaults to ${ENV_TOOL} or PATH")
    ap.add_argument("--codes", type=int, default=3, help="guard codes to queue (default: 3, ~90s)")
    ap.add_argument("--loginid", type=int, default=random.randint(1, 2**31 - 1),
                    help="Steam LogonID; keep it unique if instances run in parallel")
    ap.add_argument("--time-offset", type=int, default=None,
                    help="local clock error in seconds; auto-detected when omitted")
    ap.add_argument("--dry-run", action="store_true", help="print the command and exit")
    args = ap.parse_args()

    untrusted = untrusted_context()

    username = None if args.anonymous else (args.username or os.environ.get(ENV_USER) or None)

    guard_codes: list[str] = []
    secrets: list[str] = []
    password = ""

    if username:
        if untrusted:
            die(
                f"refusing to authenticate in {untrusted}: that run executes code this "
                "repository does not control, and Steam credentials would be reachable "
                "from it. Use --anonymous for the dedicated server instead."
            )
        password = os.environ.get(ENV_PASS, "")
        if not password:
            die(f"{ENV_PASS} is not set; the password is never accepted as an argument")

        explicit = args.maFile or os.environ.get(steam_guard.ENV_PATH) or os.environ.get(steam_guard.ENV_B64)
        try:
            ma = steam_guard.load(args.maFile)
        except GuardError as err:
            if explicit:
                die(str(err))
            print("warning: no maFile configured, Steam will send a "
                  "mobile-confirmation push instead", file=sys.stderr)
            print("warning: approve it on the phone or the login stalls", file=sys.stderr)
        else:
            guard_codes = steam_guard.codes(ma, args.codes, args.time_offset)
            secrets = [password, *guard_codes]
            print(f"maFile: {steam_guard.describe(ma)}")

    if args.dry_run:
        cmd = build_argv(Path(args.tool or f"<DepotDownloader; set ${ENV_TOOL}>"),
                         args, username)
        print("$ " + " ".join(cmd))
        print(f"  auth: {len(guard_codes)} guard code(s) via stdin, password withheld")
        return 0

    tool = find_tool(args.tool)
    cmd = build_argv(tool, args, username)

    args.dest.mkdir(parents=True, exist_ok=True)
    return run(cmd, stdin_payload(password, guard_codes), tuple(secrets))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GuardError as err:
        die(str(err))
    except KeyboardInterrupt:
        sys.exit(130)