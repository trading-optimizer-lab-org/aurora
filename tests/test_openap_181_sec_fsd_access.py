from __future__ import annotations

import hashlib
import runpy
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked


class _Response:
    def __init__(self, status_code: int, payload: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload

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

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield self._payload


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


def _module():
    return import_module("aurora.research.openap_181.sec_fsd_access")


def test_official_fsd_download_records_origin_access_headers_hash_and_size(tmp_path):
    module = _module()
    payload = b"PK\x03\x04fixture-sec-fsd"
    session = _Session([_Response(200, payload)])

    summary = module.download_official_sec_fsd_archives(
        ("2024q1",),
        tmp_path / "zips",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(),
    )

    expected_url = (
        "https://www.sec.gov/files/dera/data/"
        "financial-statement-data-sets/2024q1.zip"
    )
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "quarters_requested": 1,
    }
    assert (tmp_path / "zips" / "2024q1.zip").read_bytes() == payload
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest.to_dict(orient="records") == [
        {
            "source_id": "sec_fsd_2024q1",
            "source_url": expected_url,
            "access_url": expected_url,
            "access_method": "sec_official_direct_fair_access",
            "period": "2024q1",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "retrieved_at": manifest.loc[0, "retrieved_at"],
            "status": "downloaded",
            "http_status": 200,
            "failure_reason": "",
        }
    ]
    call = session.calls[0]
    assert call["url"] == expected_url
    assert call["headers"] == {
        "User-Agent": "Aurora Research https://github.com/example/aurora",
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    assert call["allow_redirects"] is True
    assert call["stream"] is True


def test_official_fsd_http_403_is_bounded_and_persisted_as_a_blocker(tmp_path):
    module = _module()
    session = _Session([_Response(403), _Response(403)])

    summary = module.download_official_sec_fsd_archives(
        ("2021q1", "2021q2"),
        tmp_path / "zips",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(0,),
    )

    assert summary == {
        "all_downloaded": False,
        "downloaded": 0,
        "failed": 1,
        "quarters_requested": 2,
    }
    assert len(session.calls) == 2
    assert not list((tmp_path / "zips").glob("*.part"))
    assert not list((tmp_path / "zips").glob("*.zip"))
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest["period"].tolist() == ["2021q1"]
    assert manifest.loc[0, "status"] == "failed"
    assert manifest.loc[0, "http_status"] == 403
    assert manifest.loc[0, "failure_reason"] == "http_403_after_2_attempts"


def test_sec_fsd_access_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_181_sec_fsd_access.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 SEC FSD access"):
        runpy.run_path(str(script), run_name="__main__")
