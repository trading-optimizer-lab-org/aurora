from __future__ import annotations

import hashlib
import runpy
import sys
import zipfile
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked


def _module():
    return import_module("aurora.research.openap_181.sec_fsd_inputs")


def _write_fsd_zip(path):
    tables = {
        "sub.txt": pd.DataFrame(
            [
                {
                    "adsh": "0001-24-000001",
                    "cik": 1,
                    "sic": 3571,
                    "form": "10-Q",
                    "period": 20240331,
                    "filed": 20240501,
                    "accepted": 20240501120000,
                },
                {
                    "adsh": "0002-24-000001",
                    "cik": 2,
                    "sic": 6020,
                    "form": "8-K",
                    "period": 20240331,
                    "filed": 20240502,
                    "accepted": 20240502120000,
                },
            ]
        ),
        "tag.txt": pd.DataFrame(
            [
                {
                    "tag": "Assets",
                    "version": "us-gaap/2024",
                    "custom": 0,
                    "abstract": 0,
                },
                {
                    "tag": "IrrelevantTag",
                    "version": "us-gaap/2024",
                    "custom": 0,
                    "abstract": 0,
                },
            ]
        ),
        "pre.txt": pd.DataFrame(
            [
                {
                    "adsh": "0001-24-000001",
                    "line": 1,
                    "stmt": "BS",
                    "tag": "Assets",
                    "version": "us-gaap/2024",
                },
                {
                    "adsh": "0001-24-000001",
                    "line": 2,
                    "stmt": "BS",
                    "tag": "IrrelevantTag",
                    "version": "us-gaap/2024",
                },
            ]
        ),
        "num.txt": pd.DataFrame(
            [
                {
                    "adsh": "0001-24-000001",
                    "tag": "Assets",
                    "version": "us-gaap/2024",
                    "coreg": "",
                    "ddate": 20240331,
                    "qtrs": 0,
                    "uom": "USD",
                    "value": 100.0,
                },
                {
                    "adsh": "0001-24-000001",
                    "tag": "IrrelevantTag",
                    "version": "us-gaap/2024",
                    "coreg": "",
                    "ddate": 20240331,
                    "qtrs": 0,
                    "uom": "USD",
                    "value": 999.0,
                },
            ]
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, frame in tables.items():
            archive.writestr(name, frame.to_csv(sep="\t", index=False))


def test_prepare_fsd_batch_reduces_zip_and_builds_cik_cohort(tmp_path):
    module = _module()
    zip_dir = tmp_path / "zips"
    output = tmp_path / "outputs"
    zip_dir.mkdir()
    archive = zip_dir / "2024q1.zip"
    _write_fsd_zip(archive)
    payload = archive.read_bytes()
    manifest = pd.DataFrame(
        [
            {
                "source_id": "sec_fsd_2024q1",
                "source_url": (
                    "https://www.sec.gov/files/dera/data/"
                    "financial-statement-data-sets/2024q1.zip"
                ),
                "period": "2024q1",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "retrieved_at": "2026-08-09T08:00:00Z",
                "status": "downloaded",
                "failure_reason": "",
            }
        ]
    )

    summary = module.prepare_sec_fsd_batch_inputs(
        zip_dir,
        manifest,
        output,
        start_quarter="2024q1",
        end_quarter="2024q1",
        formation_start="2024-05-31",
        formation_end="2024-06-30",
    )

    assert summary == {
        "expected_rows": 2,
        "formation_months": 2,
        "identity_rows": 1,
        "num_rows": 1,
        "pre_rows": 1,
        "quarters": 1,
        "sub_rows": 1,
        "tag_rows": 1,
    }
    reduced_num = pd.read_csv(output / "num.csv")
    identity = pd.read_csv(output / "identity.csv")
    expected = pd.read_csv(output / "expected_universe.csv")
    assert reduced_num["tag"].tolist() == ["Assets"]
    assert identity["security_id"].tolist() == ["CIK-0000000001"]
    assert expected["security_id"].eq("CIK-0000000001").all()
    assert expected["exchange"].eq("unknown_not_available_in_sec_fsd").all()
    assert expected["security_type"].eq("unknown_not_available_in_sec_fsd").all()


def test_quarter_range_rejects_reversed_or_unbounded_requests():
    module = _module()

    with pytest.raises(ValueError, match="start quarter"):
        module.bounded_quarters("2024q2", "2024q1")
    with pytest.raises(ValueError, match="at most 16"):
        module.bounded_quarters("2020q1", "2024q1")


def test_sec_fsd_preparation_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_181_sec_fsd_inputs.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 SEC FSD preparation"):
        runpy.run_path(str(script), run_name="__main__")
