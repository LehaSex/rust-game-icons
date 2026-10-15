
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".pipeline"
BUILD = ROOT / "build"
KERNEL_DIR = BUILD / "kernel"
VERSION_FILE = BUILD / "kernels-version.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

TERMINAL_OK = {"complete"}
TERMINAL_BAD = {"error", "timeout", "cancelled"}


def sh(args: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for f in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        if env.get(f):
            env["KAGGLE_" + f.split("_")[1]] = env[f]
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    print("$", " ".join(args), flush=True)
    proc = subprocess.run(args, env=env, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        sys.exit(f"command failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def slug() -> str:
    value = os.environ.get("KAGGLE_KERNEL_SLUG", "").strip()
    if not value:
        sys.exit("KAGGLE_KERNEL_SLUG is not set (owner/slug)")
    return value


def render() -> None:
    sys.path.insert(0, str(ROOT / ".pipeline" / "scripts"))
    from render_kernel import build_notebook

    KERNEL_DIR.mkdir(parents=True, exist_ok=True)
    nb = build_notebook(
        pipeline_py=ROOT / PIPELINE / "kernel" / "pipeline.py",
        requirements=(ROOT / PIPELINE / "kernel" / "requirements-kernel.txt").read_text(encoding="utf-8"),
    )
    (KERNEL_DIR / "pipeline.ipynb").write_text(
        json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    meta_tmpl = (ROOT / PIPELINE / "kernel" / "kernel-metadata.json.tmpl").read_text(encoding="utf-8")
    meta = meta_tmpl.replace("${KAGGLE_KERNEL_SLUG}", slug()).replace(
        "${ICONS_DELTA_SLUG}", os.environ.get("ICONS_DELTA_SLUG", "")
    )
    (KERNEL_DIR / "kernel-metadata.json").write_text(meta, encoding="utf-8")
    print(f"kernel built in {KERNEL_DIR}")


def push() -> str:
    render()
    proc = sh(["kaggle", "kernels", "push", "-p", str(KERNEL_DIR)], check=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        print("  ", line)
    version = ""
    numbered = re.search(r"kernel version (\d+)", text, re.IGNORECASE)
    if numbered:
        version = numbered.group(1)
    else:
        for token in text.replace(",", " ").split():
            if token.isdigit() and len(token) >= 10:
                version = token
                break
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(
        json.dumps({"version": version, "slug": slug(), "pushed_at": time.time()}, indent=2),
        encoding="utf-8",
    )
    print(f"version: {version or 'not recognised'}")
    return version


def kernel_state(text: str) -> str:
    """`has status "KernelWorkerStatus.RUNNING"` -> `running`; older CLI printed the bare word."""
    for pattern in (r'status\s+"?([\w.]+)"?', r"^\s*([\w.]+)\s*$"):
        found = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if found:
            return found.group(1).rsplit(".", 1)[-1].lower()
    return ""


def wait(timeout_min: int = 750) -> str:
    target = slug()
    data = json.loads(VERSION_FILE.read_text(encoding="utf-8")) if VERSION_FILE.is_file() else {}
    ref = f"{target}/{data['version']}" if data.get("version") else target
    deadline = time.time() + timeout_min * 60
    last = ""
    while time.time() < deadline:
        proc = sh(["kaggle", "kernels", "status", ref], check=False)
        text = ((proc.stdout or "") + (proc.stderr or "")).strip()
        state = kernel_state(text)
        if state != last:
            print(f"  status: {state or text}", flush=True)
            last = state
        if state in TERMINAL_OK:
            return state
        if state in TERMINAL_BAD:
            sys.exit(f"kernel finished in state {state}\n{text}")
        time.sleep(60)
    sys.exit(f"timeout after {timeout_min} min")


def fetch(dest: Path) -> None:
    data = json.loads(VERSION_FILE.read_text(encoding="utf-8")) if VERSION_FILE.is_file() else {}
    ref = f"{data.get('slug', slug())}/{data['version']}" if data.get("version") else slug()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    proc = sh(["kaggle", "kernels", "output", ref, "-p", str(dest), "--force"], check=False)
    if proc.returncode != 0:
        print((proc.stderr or "")[-600:])
        sys.exit("failed to download the kernel output")


def dataset(directory: Path, note: str = "", wait_min: int = 60) -> None:
    """Publish a new version of the private input dataset.

    `kaggle datasets version` returns as soon as the upload is accepted; the
    version is only queryable a little later, which matters because the kernel
    is pushed right after this.
    """
    if not directory.is_dir():
        sys.exit(f"not a directory: {directory}")
    if not (directory / "needed.json").is_file():
        sys.exit(f"{directory}/needed.json is missing; nothing to publish")

    cmd = ["kaggle", "datasets", "version", "-p", str(directory), "-t",
           "-r", "zip", "-m", note or f"delta {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"]
    proc = sh(cmd, check=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.strip().splitlines():
        print("  ", line)
    if proc.returncode != 0:
        sys.exit("failed to publish the dataset version")

    wait_live(directory, wait_min)


def wait_live(directory: Path, wait_min: int) -> None:
    """Wait until the dataset serves the file list we just uploaded.

    `datasets status` already answers `ready` while the new version is still
    being processed, and `datasets list -s` never matches a private dataset at
    all, so the only trustworthy signal is the uploaded manifest itself coming
    back byte for byte.
    """
    slug = slug_of_dataset(directory)
    if not slug:
        print("  no dataset id in dataset-metadata.json; skipping the readiness probe")
        return
    want = (directory / "needed.json").read_bytes()
    deadline = time.time() + wait_min * 60
    with tempfile.TemporaryDirectory() as tmp:
        while True:
            proc = sh(["kaggle", "datasets", "download", "-f", "needed.json",
                       slug, "-p", tmp, "-o", "-q"], check=False)
            got = Path(tmp) / "needed.json"
            if proc.returncode == 0 and got.is_file() and got.read_bytes() == want:
                print("dataset version is live")
                return
            if time.time() >= deadline:
                print("  note: the dataset may still be processing; the kernel will pick it up")
                return
            print("  waiting for the dataset version to go live...")
            time.sleep(30)


def slug_of_dataset(directory: Path) -> str:
    meta = directory / "dataset-metadata.json"
    if meta.is_file():
        try:
            return json.loads(meta.read_text(encoding="utf-8")).get("id", "")
        except ValueError:
            return ""
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Kaggle kernel orchestration")
    ap.add_argument("action", choices=("push", "wait", "fetch", "all", "render", "dataset"))
    ap.add_argument("--dest", type=Path, default=ROOT / "out")
    ap.add_argument("--timeout-min", type=int, default=330,
                    help="kernel wait ceiling; a GitHub job cannot exceed 6h (default 330)")
    ap.add_argument("--dir", type=Path, default=ROOT / "delta-pkg", help="dataset package to publish")
    ap.add_argument("--note", default="", help="version message for the dataset")
    args = ap.parse_args()

    if args.action == "render":
        render()
    elif args.action == "push":
        push()
    elif args.action == "wait":
        wait(args.timeout_min)
    elif args.action == "fetch":
        fetch(args.dest)
    elif args.action == "dataset":
        dataset(args.dir, args.note or f"delta {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    else:
        push()
        wait(args.timeout_min)
        fetch(args.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())