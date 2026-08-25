"""CLI for stable, read-only catalog authority watchdog snapshots."""
from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .catalog_authority_ledger import extract_authority_comment_records


_ANCHOR_PATH = Path("config/catalog_authority_anchor_v1.json")
_DISABLED_PATH = Path("watchdog-disabled")
_AUTHORITY_NUMBER_PATH = Path("authority-number")
_COMMENT_SNAPSHOT_PATHS = (Path("authority-comments-1.json"), Path("authority-comments-2.json"))
_QUEUED_SNAPSHOT_PATHS = (
    Path("actions-runs-queued-1.json"),
    Path("actions-runs-queued-2.json"),
)
_IN_PROGRESS_SNAPSHOT_PATHS = (
    Path("actions-runs-in_progress-1.json"),
    Path("actions-runs-in_progress-2.json"),
)
_NONTERMINAL_STATES = frozenset({"reserved", "running", "recovering", "waiting_retry"})


def _fetch_snapshot(endpoint: str, output_path: Path) -> None:
    with output_path.open("wb") as output:
        subprocess.run(
            ("gh", "api", "--paginate", "--slurp", endpoint),
            check=True,
            stdout=output,
        )


def _assert_byte_stable(first: Path, second: Path, reason: str) -> None:
    if first.read_bytes() != second.read_bytes():
        raise SystemExit(reason)


def snapshot() -> None:
    anchor = json.loads(_ANCHOR_PATH.read_text("utf-8"))
    if anchor.get("production_enabled") is not True:
        _DISABLED_PATH.write_text("true\n", encoding="utf-8")
        return

    number = anchor.get("issue_number")
    if not isinstance(number, int) or number < 1:
        raise SystemExit("CATALOG_WATCHDOG_AUTHORITY_ANCHOR_INVALID")
    _AUTHORITY_NUMBER_PATH.write_text(f"{number}\n", encoding="utf-8")

    if _DISABLED_PATH.is_file():
        return

    authority_number = _AUTHORITY_NUMBER_PATH.read_text("utf-8").strip()
    repository = os.environ["GITHUB_REPOSITORY"]
    for snapshot_number in (1, 2):
        _fetch_snapshot(
            f"repos/{repository}/issues/{authority_number}/comments?per_page=100",
            Path(f"authority-comments-{snapshot_number}.json"),
        )
        _fetch_snapshot(
            f"repos/{repository}/actions/runs?status=queued&per_page=100",
            Path(f"actions-runs-queued-{snapshot_number}.json"),
        )
        _fetch_snapshot(
            f"repos/{repository}/actions/runs?status=in_progress&per_page=100",
            Path(f"actions-runs-in_progress-{snapshot_number}.json"),
        )

    _assert_byte_stable(
        _COMMENT_SNAPSHOT_PATHS[0],
        _COMMENT_SNAPSHOT_PATHS[1],
        "CATALOG_WATCHDOG_LEDGER_SNAPSHOT_UNSTABLE",
    )
    _assert_byte_stable(
        _QUEUED_SNAPSHOT_PATHS[0],
        _QUEUED_SNAPSHOT_PATHS[1],
        "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_UNSTABLE",
    )
    _assert_byte_stable(
        _IN_PROGRESS_SNAPSHOT_PATHS[0],
        _IN_PROGRESS_SNAPSHOT_PATHS[1],
        "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_UNSTABLE",
    )


def select() -> None:
    empty = {"include": []}
    if _DISABLED_PATH.is_file():
        matrix = empty
    else:
        pages = json.loads(_COMMENT_SNAPSHOT_PATHS[0].read_text("utf-8"))
        comments = [row for page in pages for row in page]
        records = extract_authority_comment_records(
            comments,
            expected_author="github-actions[bot]",
        )
        latest: dict[str, Any] = {}
        for record in records:
            latest[str(record.authority_id)] = record

        run_states: dict[int, str] = {}
        for expected_status, snapshot_path in (
            ("queued", _QUEUED_SNAPSHOT_PATHS[0]),
            ("in_progress", _IN_PROGRESS_SNAPSHOT_PATHS[0]),
        ):
            run_pages = json.loads(snapshot_path.read_text("utf-8"))
            for page in run_pages:
                for run in (page.get("workflow_runs") or []):
                    run_id = run.get("id")
                    status = run.get("status")
                    if not isinstance(run_id, int) or status != expected_status:
                        raise SystemExit("CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID")
                    if run_id in run_states:
                        raise SystemExit("CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID")
                    run_states[run_id] = status

        include = []
        for authority_id, record in sorted(latest.items()):
            if record.state.value not in _NONTERMINAL_STATES:
                continue
            if run_states.get(record.run_id) in {"queued", "in_progress"}:
                continue
            include.append(
                {
                    "authority_id": authority_id,
                    "issue_number": record.request_issue_number,
                }
            )
        if len(include) > 1:
            raise SystemExit("CATALOG_WATCHDOG_ACTIVE_AUTHORITY_CONFLICT")
        matrix = {"include": include}

    encoded = json.dumps(matrix, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-16-le")) > 512 * 1024:
        raise SystemExit("CATALOG_WATCHDOG_MATRIX_TOO_LARGE")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"matrix={encoded}\n")
        output.write(f"matrix_count={len(matrix['include'])}\n")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in {"snapshot", "select"}:
        raise SystemExit(
            "usage: python -m aurora.infra.sp500_megarun.catalog_watchdog "
            "{snapshot,select}"
        )
    if arguments[0] == "snapshot":
        snapshot()
    else:
        select()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
