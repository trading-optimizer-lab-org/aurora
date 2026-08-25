from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    append_authority_record,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "aurora.infra.sp500_megarun.catalog_watchdog"
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
BOT = "github-actions[bot]"
REPOSITORY = "trading-optimizer-lab-org/aurora"
HEAD = "a" * 40
_MISSING = object()

FAKE_GH_SOURCE = r'''
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


config = json.loads(Path(os.environ["FAKE_GH_CONFIG"]).read_text("utf-8"))
calls_path = Path(os.environ["FAKE_GH_CALLS"])
calls = json.loads(calls_path.read_text("utf-8")) if calls_path.exists() else []
args = sys.argv[1:]
if args:
    args[-1] = args[-1].strip('"')
endpoint = args[-1]
if "/comments?" in endpoint:
    key = "comments"
elif "status=queued" in endpoint:
    key = "queued"
elif "status=in_progress" in endpoint:
    key = "in_progress"
else:
    raise SystemExit(f"unexpected endpoint: {endpoint}")
index = sum(1 for call in calls if call["key"] == key)
calls.append({"key": key, "args": args})
calls_path.write_text(json.dumps(calls), encoding="utf-8")
responses = config["responses"][key]
response = responses[min(index, len(responses) - 1)]
raw = response.encode("utf-8") if isinstance(response, str) else json.dumps(
    response, separators=(",", ":")
).encode("utf-8")
sys.stdout.buffer.write(raw)
'''


def _raw(payload: object, *, ending: str = "\n") -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ending


def _record_chain(count: int):
    previous = None
    records = []
    for index in range(count):
        record = append_authority_record(
            previous=previous,
            state=AuthorityState.RESERVED,
            authority_id=UUID(f"018f47a2-6e91-7c34-8000-0000000001{index + 1:02d}"),
            request_issue_number=300 + index,
            campaign_id=f"{index + 1:064x}",
            request_sha256=f"{index + 11:064x}",
            science_sha256=f"{index + 21:064x}",
            execution_plan_sha256=f"{index + 31:064x}",
            execution_protocol_sha256=f"{index + 41:064x}",
            run_id=1000 + index,
            run_attempt=1,
            writer_job_id="reserve",
            writer_job_database_id=2000 + index,
            protected_commit_sha=HEAD,
            created_at=NOW + timedelta(minutes=index),
        )
        records.append(record)
        previous = record
    return tuple(records)


def _comment(record, comment_id: int) -> dict[str, object]:
    created_at = (NOW + timedelta(minutes=comment_id)).isoformat().replace("+00:00", "Z")
    return {
        "id": comment_id,
        "user": {"login": BOT},
        "body": record.to_comment(),
        "created_at": created_at,
        "updated_at": created_at,
    }


def _run_pages(*pages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"workflow_runs": page} for page in pages] or [{"workflow_runs": []}]


def _stable_responses(
    *,
    comments: list[list[dict[str, object]]],
    queued: list[dict[str, object]],
    in_progress: list[dict[str, object]],
) -> dict[str, list[str]]:
    return {
        "comments": [_raw(comments)] * 2,
        "queued": [_raw(queued)] * 2,
        "in_progress": [_raw(in_progress)] * 2,
    }


def _write_anchor(tmp_path: Path, *, production_enabled: bool) -> None:
    config = tmp_path / "config"
    config.mkdir()
    payload: dict[str, object] = {"production_enabled": production_enabled}
    if production_enabled:
        payload["issue_number"] = 161
    (config / "catalog_authority_anchor_v1.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _install_fake_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, list[str]],
) -> Path:
    import importlib

    config_path = tmp_path / "fake-gh-config.json"
    config_path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    calls_path = tmp_path / "fake-gh-calls.json"
    calls_path.write_text("[]", encoding="utf-8")
    worker = tmp_path / "fake_gh.py"
    worker.write_text(FAKE_GH_SOURCE, encoding="utf-8")
    if os.name == "nt":
        executable = tmp_path / "gh.cmd"
        executable.write_text(
            f'@"{sys.executable}" "{worker}" %*\n',
            encoding="utf-8",
        )
    else:
        executable = tmp_path / "gh"
        executable.write_text(
            "#!/usr/bin/env python3\n" + FAKE_GH_SOURCE,
            encoding="utf-8",
        )
        executable.chmod(0o755)
    monkeypatch.setenv("FAKE_GH_CONFIG", str(config_path))
    monkeypatch.setenv("FAKE_GH_CALLS", str(calls_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    if os.name == "nt":
        module = importlib.import_module(MODULE_NAME)
        real_run = module.subprocess.run

        def run_fake_gh(command, **kwargs):
            if command and command[0] == "gh":
                cmd_arguments = [str(executable), *command[1:-1], f'"{command[-1]}"']
                return real_run(["cmd.exe", "/d", "/c", *cmd_arguments], **kwargs)
            return real_run(command, **kwargs)

        monkeypatch.setattr(module.subprocess, "run", run_fake_gh)
    return calls_path


def _run_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str) -> int:
    import importlib

    monkeypatch.chdir(tmp_path)
    if command == "select" and "GITHUB_OUTPUT" not in os.environ:
        monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    module = importlib.import_module(MODULE_NAME)
    return module.main([command])


def _read_calls(calls_path: Path) -> list[dict[str, object]]:
    return json.loads(calls_path.read_text("utf-8"))


def test_snapshot_fetches_exactly_six_paginated_endpoints_and_preserves_raw_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_anchor(tmp_path, production_enabled=True)
    raw_payloads = {
        "comments": "[\r\n  [{\"body\":\"comments\"}],\r\n  []\r\n]\r\n",
        "queued": "[{\"workflow_runs\":[]}, {\"workflow_runs\":[]}]\r\n",
        "in_progress": "[{\"workflow_runs\":[]}, {\"workflow_runs\":[]}]\n",
    }
    calls_path = _install_fake_gh(
        tmp_path,
        monkeypatch,
        {key: [value, value] for key, value in raw_payloads.items()},
    )

    assert _run_cli(monkeypatch, tmp_path, "snapshot") == 0

    calls = _read_calls(calls_path)
    assert [call["key"] for call in calls] == [
        "comments",
        "queued",
        "in_progress",
        "comments",
        "queued",
        "in_progress",
    ]
    assert [call["args"] for call in calls] == [
        [
            "api",
            "--paginate",
            "--slurp",
            "repos/trading-optimizer-lab-org/aurora/issues/161/comments?per_page=100",
        ],
        [
            "api",
            "--paginate",
            "--slurp",
            "repos/trading-optimizer-lab-org/aurora/actions/runs?status=queued&per_page=100",
        ],
        [
            "api",
            "--paginate",
            "--slurp",
            "repos/trading-optimizer-lab-org/aurora/actions/runs?status=in_progress&per_page=100",
        ],
    ] * 2
    assert (tmp_path / "authority-comments-1.json").read_bytes() == raw_payloads[
        "comments"
    ].encode("utf-8")
    assert (tmp_path / "authority-comments-2.json").read_bytes() == raw_payloads[
        "comments"
    ].encode("utf-8")
    assert (tmp_path / "actions-runs-queued-1.json").read_bytes() == raw_payloads[
        "queued"
    ].encode("utf-8")
    assert (tmp_path / "actions-runs-in_progress-2.json").read_bytes() == raw_payloads[
        "in_progress"
    ].encode("utf-8")


@pytest.mark.parametrize(
    ("changing", "reason"),
    [
        ("comments", "CATALOG_WATCHDOG_LEDGER_SNAPSHOT_UNSTABLE"),
        ("queued", "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_UNSTABLE"),
        ("in_progress", "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_UNSTABLE"),
    ],
)
def test_snapshot_rejects_each_unstable_byte_snapshot(
    changing: str,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_anchor(tmp_path, production_enabled=True)
    stable = {
        "comments": _raw([[]]),
        "queued": _raw(_run_pages()),
        "in_progress": _raw(_run_pages()),
    }
    changed = dict(stable)
    changed[changing] = stable[changing] + " "
    calls_path = _install_fake_gh(
        tmp_path,
        monkeypatch,
        {
            key: [stable[key], changed[key]]
            if key == changing
            else [stable[key], stable[key]]
            for key in stable
        },
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "snapshot")

    assert exc_info.value.code == reason
    assert len(_read_calls(calls_path)) == 6


def test_snapshot_disabled_writes_marker_without_calling_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_anchor(tmp_path, production_enabled=False)
    calls_path = _install_fake_gh(
        tmp_path,
        monkeypatch,
        {"comments": [], "queued": [], "in_progress": []},
    )

    assert _run_cli(monkeypatch, tmp_path, "snapshot") == 0

    assert (tmp_path / "watchdog-disabled").read_text("utf-8") == "true\n"
    assert _read_calls(calls_path) == []


def test_select_reads_second_pages_and_emits_complete_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _record_chain(3)
    comments = [[_comment(records[0], 1), _comment(records[1], 2)], [_comment(records[2], 3)]]
    queued = _run_pages(
        [{"id": records[0].run_id, "status": "queued"}],
        [{"id": 9000, "status": "queued"}],
    )
    in_progress = _run_pages(
        [],
        [{"id": records[1].run_id, "status": "in_progress"}],
    )
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(comments=comments, queued=queued, in_progress=in_progress),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert _run_cli(monkeypatch, tmp_path, "select") == 0

    matrix = {
        "include": [
            {
                "authority_id": str(records[2].authority_id),
                "issue_number": records[2].request_issue_number,
            }
        ]
    }
    encoded = json.dumps(matrix, sort_keys=True, separators=(",", ":"))
    assert output.read_text("utf-8") == f"matrix={encoded}\nmatrix_count=1\n"


def test_select_rejects_run_with_wrong_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record_chain(1)[0]
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(record, 1)]],
            queued=_run_pages([{"id": record.run_id, "status": "in_progress"}]),
            in_progress=_run_pages(),
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID"


@pytest.mark.parametrize(
    "workflow_runs",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param(None, id="null"),
        pytest.param({}, id="dict"),
        pytest.param("not-a-list", id="string"),
        pytest.param(1, id="number"),
    ],
)
@pytest.mark.parametrize("snapshot_status", ["queued", "in_progress"])
def test_select_rejects_invalid_workflow_runs_for_each_status(
    workflow_runs: object,
    snapshot_status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record_chain(1)[0]
    page = {} if workflow_runs is _MISSING else {"workflow_runs": workflow_runs}
    snapshots = {
        "queued": _run_pages(),
        "in_progress": _run_pages(),
    }
    snapshots[snapshot_status] = [page]
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(record, 1)]],
            queued=snapshots["queued"],
            in_progress=snapshots["in_progress"],
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID"


@pytest.mark.parametrize(
    "run_id",
    [
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(None, id="null"),
        pytest.param("1", id="string"),
        pytest.param(1.0, id="float"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
def test_select_rejects_non_positive_or_non_integer_run_ids(
    run_id: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record_chain(1)[0]
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(record, 1)]],
            queued=_run_pages([{"id": run_id, "status": "queued"}]),
            in_progress=_run_pages(),
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID"


@pytest.mark.parametrize("duplicate_kind", ["pages", "states"])
def test_select_rejects_duplicate_run_ids_across_pages_or_states(
    duplicate_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record_chain(1)[0]
    if duplicate_kind == "pages":
        queued = _run_pages(
            [{"id": 7000, "status": "queued"}],
            [{"id": 7000, "status": "queued"}],
        )
        in_progress = _run_pages()
    else:
        queued = _run_pages([{"id": 7000, "status": "queued"}])
        in_progress = _run_pages([{"id": 7000, "status": "in_progress"}])
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(record, 1)]], queued=queued, in_progress=in_progress
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_ACTIONS_SNAPSHOT_INVALID"


def test_select_rejects_two_active_authorities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    records = _record_chain(2)
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(records[0], 1), _comment(records[1], 2)]],
            queued=_run_pages(),
            in_progress=_run_pages(),
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_ACTIVE_AUTHORITY_CONFLICT"


def test_select_rejects_matrix_over_512_kibibytes_utf16(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record_chain(1)[0]
    _write_anchor(tmp_path, production_enabled=True)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        _stable_responses(
            comments=[[_comment(record, 1)]], queued=_run_pages(), in_progress=_run_pages()
        ),
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")
    import importlib

    module = importlib.import_module(MODULE_NAME)
    huge_record = SimpleNamespace(
        authority_id="x" * (512 * 1024),
        request_issue_number=1,
        run_id=record.run_id,
        state=SimpleNamespace(value="reserved"),
    )
    monkeypatch.setattr(
        module,
        "extract_authority_comment_records",
        lambda comments, *, expected_author: (huge_record,),
    )
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, tmp_path, "select")

    assert exc_info.value.code == "CATALOG_WATCHDOG_MATRIX_TOO_LARGE"


def test_select_disabled_emits_empty_matrix_without_reading_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_anchor(tmp_path, production_enabled=False)
    _install_fake_gh(
        tmp_path,
        monkeypatch,
        {"comments": [], "queued": [], "in_progress": []},
    )
    _run_cli(monkeypatch, tmp_path, "snapshot")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert _run_cli(monkeypatch, tmp_path, "select") == 0

    assert output.read_text("utf-8") == 'matrix={"include":[]}\nmatrix_count=0\n'
