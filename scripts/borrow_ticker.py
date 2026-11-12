"""Start the borrow logger on time without relying on GitHub's cron, which skips and delays scheduled runs.

One run of the ticker workflow sleeps until each start time and dispatches borrow-logger.yml. Before the
6-hour job limit it dispatches its own successor, so the chain covers every day with work. A cron kick every
hour restarts the chain if it ever breaks; while the chain is alive that kick exits at once.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc  # all arithmetic in UTC: same-zone subtraction in Python ignores a DST change
SNAPS = [(h, m) for h in range(4, 20) for m in (5, 35)] + [(15, 45)]  # TradeZero's locate hours + decision time
DAILY = (5, 30)  # threshold lists of the prior session are out by then
LIFE = timedelta(hours=5, minutes=40)  # under the 6-hour job limit
REPLAY = timedelta(minutes=30)  # the logger skips a snapshot it already took, so a replay is harmless
AHEAD = timedelta(hours=12)  # keep the chain only while there is work within this
CATCHUP = timedelta(hours=3)  # a late successor still starts the slots it missed since its parent ended
RETRIES = 2  # GitHub failed two logger runs at startup on 2026-11-11 (15:35, 15:45) and lost the decision quotes


def events(day: date) -> list[tuple[datetime, str]]:
    """(New York time, mode) of one day: snapshots Monday-Friday, the daily files Tuesday-Saturday."""
    at = lambda h, m: datetime(day.year, day.month, day.day, h, m, tzinfo=NY)  # noqa: E731
    out = [(at(h, m), "snap") for h, m in SNAPS] if day.weekday() < 5 else []
    if 1 <= day.weekday() <= 5:
        out.append((at(*DAILY), "daily"))
    return sorted(out)


def upcoming(now: datetime, until: datetime) -> list[tuple[datetime, str]]:
    first = now.astimezone(NY).date()
    days = [first + timedelta(days=i) for i in range(-1, (until - now).days + 2)]
    return sorted(e for d in days for e in events(d) if now <= e[0] < until)


def gh(*args: str) -> str:
    """Three tries with a timeout: one GitHub hiccup must not break the chain."""
    for i in range(3):
        try:
            return subprocess.run(["gh", *args, "--repo", os.environ["GITHUB_REPOSITORY"]],
                                  check=True, capture_output=True, text=True, timeout=60).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if i == 2:
                raise
            time.sleep(20)
    return ""


def sleep_until(at: datetime) -> None:
    time.sleep(max(0.0, at.timestamp() - time.time()))


def start_logger(mode: str) -> str:
    """Dispatch the logger and watch that run until it starts; dispatch again if GitHub fails it at startup."""
    for _ in range(RETRIES + 1):
        sent = datetime.now(UTC) - timedelta(seconds=10)
        gh("workflow", "run", "borrow-logger.yml", "--ref", "main", "-f", f"mode={mode}")
        state = "unconfirmed"
        for _ in range(16):  # a startup failure took up to 6 minutes to show
            time.sleep(30)
            runs = json.loads(gh("run", "list", "--workflow", "borrow-logger.yml", "--event", "workflow_dispatch",
                                 "--limit", "5", "--json", "createdAt,status,conclusion"))
            mine = sorted((r for r in runs if datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= sent),
                          key=lambda r: r["createdAt"])
            if not mine or mine[0]["status"] in ("queued", "requested", "waiting", "pending"):
                continue
            state = mine[0]["conclusion"] or mine[0]["status"]
            break
        if state != "startup_failure":
            return state
    return state


def plan(start: datetime, now: datetime) -> list[tuple[datetime, str]]:
    """The start times from start to start + LIFE; the missed ones collapse to the latest of each mode, run now."""
    due = upcoming(start, start + LIFE)
    late = {m: (t, m) for t, m in due if t <= now}
    return sorted(late.values()) + [e for e in due if e[0] > now]


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
    now = datetime.now(UTC)
    since = os.environ.get("SINCE", "")  # the parent's end: no start time falls between two runs
    start = now - REPLAY  # a fresh chain also starts what the broken one missed lately
    if since and now - datetime.fromisoformat(since) < CATCHUP:
        start = datetime.fromisoformat(since).astimezone(UTC)
    if not upcoming(start, start + AHEAD):
        print("no logger run within 12 hours: the chain stops until a cron kick", flush=True)
        return 0
    for at, mode in plan(start, now):
        sleep_until(at)
        try:
            state = start_logger(mode)
        except Exception as e:  # one failed start must not stop the later ones nor the successor
            print(f"{at.astimezone(NY):%a %H:%M} {mode}: failed {type(e).__name__}", flush=True)
            continue
        print(f"{at.astimezone(NY):%a %H:%M} {mode}: {state}", flush=True)
    end = start + LIFE
    sleep_until(end)
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
