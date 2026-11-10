"""Start the borrow logger on time without relying on GitHub's cron, which skips and delays scheduled runs.

One run of the ticker workflow sleeps until each start time and dispatches borrow-logger.yml. Before the
6-hour job limit it dispatches its own successor, so the chain covers every day with work. A cron kick every
2 hours restarts the chain if it ever breaks; while the chain is alive that kick exits at once.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SNAPS = [(h, m) for h in range(4, 20) for m in (5, 35)] + [(15, 45)]  # TradeZero's locate hours + decision time
DAILY = (5, 30)  # threshold lists of the prior session are out by then
LIFE = timedelta(hours=5, minutes=40)  # under the 6-hour job limit
REPLAY = timedelta(minutes=30)  # the logger skips a snapshot it already took, so a replay is harmless
AHEAD = timedelta(hours=12)  # keep the chain only while there is work within this


def events(day: datetime) -> list[tuple[datetime, str]]:
    """(New York time, mode) of one day: snapshots Monday-Friday, the daily files Tuesday-Saturday."""
    at = lambda h, m: datetime(day.year, day.month, day.day, h, m, tzinfo=NY)  # noqa: E731
    out = [(at(h, m), "snap") for h, m in SNAPS] if day.weekday() < 5 else []
    if 1 <= day.weekday() <= 5:
        out.append((at(*DAILY), "daily"))
    return sorted(out)


def upcoming(now: datetime, until: datetime) -> list[tuple[datetime, str]]:
    days = [now + timedelta(days=i) for i in range((until - now).days + 2)]
    return [e for d in days for e in events(d) if now <= e[0] < until]


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args, "--repo", os.environ["GITHUB_REPOSITORY"]],
                          check=True, capture_output=True, text=True).stdout


def older_twin(me: int, parent: str, runs: list[dict]) -> bool:
    """Another queued or running ticker created first and is not the one that started this run: it keeps the chain."""
    return any(r["databaseId"] < me and str(r["databaseId"]) != parent for r in runs)


def main() -> int:
    me, parent = int(os.environ["GITHUB_RUN_ID"]), os.environ.get("PARENT", "")
    running = [r for st in ("in_progress", "queued") for r in json.loads(gh(
        "run", "list", "--workflow", "borrow-ticker.yml", "--status", st, "--json", "databaseId"))]
    if older_twin(me, parent, running):
        print("the chain is alive in another run", flush=True)
        return 0
    since = os.environ.get("SINCE", "")  # the parent's end: no start time falls between two runs
    start = datetime.now(NY) - REPLAY  # a fresh chain also starts what the broken one missed lately
    if since and datetime.now(NY) - datetime.fromisoformat(since) < timedelta(minutes=30):
        start = datetime.fromisoformat(since).astimezone(NY)
    if not upcoming(start, start + AHEAD):
        print("no logger run within 12 hours: the chain stops until a cron kick", flush=True)
        return 0
    for at, mode in upcoming(start, start + LIFE):
        time.sleep(max(0.0, (at - datetime.now(NY)).total_seconds()))
        gh("workflow", "run", "borrow-logger.yml", "--ref", "main", "-f", f"mode={mode}")
        print(f"{at:%a %H:%M} {mode}: started", flush=True)
    end = start + LIFE
    time.sleep(max(0.0, (end - datetime.now(NY)).total_seconds()))
    if upcoming(end, end + AHEAD):
        gh("workflow", "run", "borrow-ticker.yml", "--ref", "main",
           "-f", f"parent={me}", "-f", f"since={end.isoformat()}")
        print("next ticker started", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # the public log shows the error type only
        print(f"failed: {type(e).__name__}", flush=True)
        sys.exit(1)
