from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRoutingCommandV1,
)

from test_catalog_controller import NOW, _empty_ledger, _queue_evidence
from test_catalog_controller_routing import _prerequisites


ROOT = Path(__file__).resolve().parents[1]


def test_route_cli_emits_only_bounded_nonprivileged_outputs(tmp_path: Path) -> None:
    command = CatalogRoutingCommandV1(
        request_sha256="a" * 64,
        request_issue_number=101,
        campaign_id="b" * 64,
        queue=_queue_evidence(),
        ledger=_empty_ledger(),
        prerequisites=_prerequisites(),
        verified_github_now=NOW,
    )
    source = tmp_path / "route-input.json"
    result_path = tmp_path / "route-decision.json"
    github_output = tmp_path / "github-output.txt"
    source.write_text(command.model_dump_json() + "\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT.parent)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/route_catalog_run.py"),
            "--input",
            str(source),
            "--output",
            str(result_path),
            "--github-output",
            str(github_output),
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    decision = json.loads(result_path.read_text(encoding="utf-8"))
    assert decision["outcome"] == "eligible"
    assert decision["needs_live_audit"] is True
    lines = github_output.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "needs_live_audit=true",
        "outcome=eligible",
        "reason_code=CATALOG_LIVE_AUDIT_REQUIRED",
        f"route_sha256={decision['route_sha256']}",
        "authority_id=",
    ]
    assert all("source" not in line and "capacity" not in line for line in lines)


def test_route_cli_has_no_command_path_or_network_surface() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/route_catalog_run.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    for forbidden in ("--command", "--workflow", "--repository", "--url", "--token"):
        assert forbidden not in result.stdout
