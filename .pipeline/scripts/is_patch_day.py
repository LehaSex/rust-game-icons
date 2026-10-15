"""Decide whether today is a Rust patch day.

Rust force-updates on the first Tuesday of every month at 19:00 UTC. The
workflow is scheduled on days 1-7 at 19:10 UTC because cron cannot express
"first Tuesday" -- GitHub's day-of-month and day-of-week fields are OR-ed
together, not AND-ed, so `1-7 * 1` would fire on every Monday of the week too.

This narrows the seven candidate runs down to one.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ENV_TIME = "PATCH_WEEKDAY"
ENV_MAX_DAY = "PATCH_MAX_DAY"


def cron_to_python(weekday: int) -> int:
    """Cron numbering (0 or 7 = Sunday) to datetime.weekday() numbering (Monday = 0)."""
    return (weekday - 1) % 7


def env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        print(f"warning: {name}={raw!r} is not a number, using {fallback}", file=sys.stderr)
        return fallback


def first_weekday_of_month(year: int, month: int, weekday: int) -> int:
    for day in range(1, 8):
        if datetime(year, month, day, tzinfo=timezone.utc).weekday() == weekday:
            return day
    raise AssertionError("every month has a first Tuesday")


def evaluate(now: datetime, weekday: int, max_day: int) -> tuple[bool, str]:
    target = first_weekday_of_month(now.year, now.month, cron_to_python(weekday))
    name = WEEKDAYS[cron_to_python(weekday)]
    in_window = 1 <= now.day <= max_day
    is_target = now.day == target
    if is_target:
        return True, f"{now.date()} is the first {name} of {now:%B %Y}"
    if not in_window:
        return False, f"{now.date()} is outside the first {max_day} days of the month"
    return False, f"{now.date()} is not the first {name} (that is the {target}th)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch-day gate")
    ap.add_argument("--weekday", type=int,
                    default=env_int(ENV_TIME, 2),
                    help="cron day of week, 0=Sun .. 6=Sat (default 2, Tuesday; $PATCH_WEEKDAY)")
    ap.add_argument("--max-day", type=int, default=env_int(ENV_MAX_DAY, 7),
                    help="largest day to consider (default 7)")
    ap.add_argument("--force", action="store_true",
                    help="always run; used by workflow_dispatch and --force")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    forced = args.force or os.environ.get("PATCH_FORCE") == "1"

    if forced:
        run, detail = True, "forced"
    else:
        run, detail = evaluate(now, args.weekday, args.max_day)

    print(f"utc now   : {now:%Y-%m-%d %H:%M:%S %Z} ({WEEKDAYS[now.weekday()]})")
    print(f"patch day : {detail}")

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as fh:
        fh.write(f"should_run={'true' if run else 'false'}\n")
        fh.write(f"reason={detail}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())