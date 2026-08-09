from __future__ import annotations

import hashlib
import json
import runpy
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked


class _Response:
    def __init__(
        self, status_code: int, payload: dict[str, object] | None = None
    ) -> None:
        self.status_code = status_code
        self.content = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else b""
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(
                f"{self.status_code} response",
                response=self,
            )


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


def _module():
    return import_module("aurora.research.openap_181.sec_companyfacts_access")


def test_companyfacts_probe_records_official_origin_headers_hash_and_concepts(tmp_path):
    module = _module()
    payload = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {}},
            "us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {}, "Assets": {}},
        },
    }
    session = _Session([_Response(200, payload)])

    summary = module.download_official_sec_companyfacts(
        ("320193",),
        tmp_path / "raw",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(),
    )

    expected_url = (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )
    expected_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "ciks_requested": 1,
    }
    assert (tmp_path / "raw" / "CIK0000320193.json").read_bytes() == expected_bytes
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest.to_dict(orient="records") == [
        {
            "source_id": "sec_companyfacts_CIK0000320193",
            "source_url": expected_url,
            "access_url": expected_url,
            "access_method": "sec_official_companyfacts_fair_access",
            "cik": "0000320193",
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "size_bytes": len(expected_bytes),
            "retrieved_at": manifest.loc[0, "retrieved_at"],
            "status": "downloaded",
            "http_status": 200,
            "failure_reason": "",
            "entity_name": "Apple Inc.",
            "us_gaap_concepts": 2,
        }
    ]
    call = session.calls[0]
    assert call["url"] == expected_url
    assert call["headers"] == {
        "User-Agent": "Aurora Research https://github.com/example/aurora",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }
    assert call["allow_redirects"] is True


def test_companyfacts_http_403_is_bounded_and_persisted_as_a_blocker(tmp_path):
    module = _module()
    session = _Session([_Response(403), _Response(403)])

    summary = module.download_official_sec_companyfacts(
        ("320193", "789019"),
        tmp_path / "raw",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(0,),
    )

    assert summary == {
        "all_downloaded": False,
        "downloaded": 0,
        "failed": 1,
        "ciks_requested": 2,
    }
    assert len(session.calls) == 2
    assert not list((tmp_path / "raw").glob("*.part"))
    assert not list((tmp_path / "raw").glob("*.json"))
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest["cik"].astype(str).str.zfill(10).tolist() == ["0000320193"]
    assert manifest.loc[0, "status"] == "failed"
    assert manifest.loc[0, "http_status"] == 403
    assert manifest.loc[0, "failure_reason"] == "http_403_after_2_attempts"


def test_companyfacts_probe_rejects_invalid_cik_and_undeclared_user_agent(tmp_path):
    module = _module()

    with pytest.raises(ValueError, match="10 numeric digits"):
        module.download_official_sec_companyfacts(
            ("not-a-cik",),
            tmp_path / "raw",
            tmp_path / "manifest.csv",
            user_agent="Aurora Research https://github.com/example/aurora",
        )
    with pytest.raises(ValueError, match="declared identity and contact"):
        module.download_official_sec_companyfacts(
            ("320193",),
            tmp_path / "raw",
            tmp_path / "manifest.csv",
            user_agent="anonymous",
        )


def test_sec_companyfacts_access_cli_fails_closed_outside_github(
    tmp_path, monkeypatch
):
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_181_sec_companyfacts_access.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 SEC CompanyFacts access"):
        runpy.run_path(str(script), run_name="__main__")
