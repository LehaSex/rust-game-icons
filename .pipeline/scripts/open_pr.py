
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".pipeline"

# Copied from out/. manifest.json is deliberately excluded: the kernel writes its
# own manifest.json there (icon counts) and it would overwrite the version stamp.
KERNEL_FILES = ["items.json", "items.compact.json", "items.desc.json",
                "items.craft.json", "items.recycle.json"]

COMMIT_FILES = KERNEL_FILES + ["manifest.json"]


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print("$", " ".join(args[:2]), "…")
    if check and proc.returncode != 0:
        sys.exit(f"git failed: {proc.stderr[-500:]}")
    return proc


def copy_delta(out: Path, repo: Path) -> list[Path]:
    copied = []
    icons = out / "icons"
    if icons.is_dir():
        for sub in ("large", "small", "webp"):
            src_root = icons / sub
            if not src_root.is_dir():
                continue
            for src in src_root.rglob("*"):
                if not src.is_file():
                    continue
                dst = repo / sub / src.relative_to(src_root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(dst)
    return copied


def commit(repo: Path, title: str, body: str) -> str:
    run(["git", "checkout", "-B", branch()], repo)
    # git add drops the whole pathspec list if one name matches nothing.
    existing = [f for f in COMMIT_FILES if (repo / f).exists()]
    run(["git", "add", "--"] + existing, repo, check=False)
    run(["git", "add", "large", "small", "webp"], repo, check=False)
    staged = run(["git", "diff", "--cached", "--name-only"], repo).stdout.split()
    if not staged:
        print("no changes — no PR needed")
        return ""
    run(["git", "-c", "user.name=github-actions[bot]", "-c", "user.email=actions@users.noreply.github.com",
         "commit", "-m", title, "-m", body], repo)
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()


def branch() -> str:
    v = os.environ.get("KERNEL_VERSION", "local")
    return f"ci/update-{v}"


def publish(repo: Path, title: str, body: str, mode: str) -> None:
    """mode: pr (open for review), merge (open and auto-merge), push (commit to main).

    Auto-merge still leaves the branch and the PR behind as an audit trail; a
    direct push does not, and leaves nothing to roll back to but the previous
    commit.
    """
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    data_repo = os.environ.get("DATA_REPO", "")
    if not token or not data_repo:
        print("no GH_PAT or DATA_REPO - nothing will be published")
        return

    run(["git", "remote", "set-url", "origin",
         f"https://x-access-token:{token}@github.com/{data_repo}.git"], repo, check=False)

    if mode == "push":
        run(["git", "push", "origin", "HEAD:main"], repo)
        print(f"pushed directly to main")
        return

    run(["git", "push", "--force", "origin", branch()], repo)
    run(["gh", "pr", "create", "--repo", data_repo, "--base", "main",
         "--head", branch(), "--title", title, "--body", body], repo, check=False)

    if mode == "merge":
        merged = run(["gh", "pr", "merge", "--repo", data_repo, "--squash",
                      "--delete-branch", "--auto", branch()], repo, check=False)
        if merged.returncode != 0:
            print("auto-merge not accepted; the PR is open and needs a manual merge")
        else:
            print("auto-merge armed; the PR merges itself once required checks pass")


def summarize(out: Path, repo: Path) -> str:
    lines = []
    man = out / "manifest.json"
    if man.is_file():
        d = json.loads(man.read_text(encoding="utf-8"))
        lines.append(f"- icons added: {d.get('count', 0)} (upscale {d.get('upscaled', 0)} of {d.get('requested', 0)})")
    for f in KERNEL_FILES:
        p = out / f
        if p.is_file():
            lines.append(f"- updated `{f}`")
    stamp = repo / "manifest.json"
    if stamp.is_file():
        try:
            lines.append(f"- game version: `{json.loads(stamp.read_text(encoding='utf-8')).get('version')}`")
        except (OSError, json.JSONDecodeError):
            pass
    if not lines:
        lines.append("- no changes")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy artifacts and publish them")
    ap.add_argument("--repo", type=Path, default=ROOT / "data")
    ap.add_argument("--out", type=Path, default=ROOT / "out")
    ap.add_argument("--title", default="chore: refresh data from the game")
    ap.add_argument("--mode", choices=("pr", "merge", "push"),
                    default=os.environ.get("PUBLISH_MODE", "pr"),
                    help="pr: open for review; merge: open and auto-merge once checks pass; "
                         "push: commit straight to main (default pr, $PUBLISH_MODE)")
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = args.out.resolve()
    if not out.is_dir():
        sys.exit(f"no output directory {out}")
    if not (repo / ".git").is_dir():
        sys.exit(f"{repo} is not a git repository")

                                                                              
                                                                              
    for f in KERNEL_FILES:
        src = out / f
        if src.is_file():
            shutil.copy2(src, repo / f)

    copied = copy_delta(out, repo)
    print(f"copied {len(copied)} icon files")

    body = (summarize(out, repo) + f"\n\nGenerated {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
            f"\n\nKernel version: {os.environ.get('KERNEL_VERSION', 'local')}")
    b = commit(repo, args.title, body)
    if b:
        publish(repo, args.title, body, args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())