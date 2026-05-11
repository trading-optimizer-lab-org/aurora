"""R156 CLI surfaces -- identity / fundamentals / macro / crypto-metrics.

The tests inject HTTP transports via the
``AU_<PROVIDER>_HTTP_<METHOD>_FACTORY`` env vars, which the CLI resolves
via ``_resolve_factory_callable``. Each test installs a fixture module
into ``sys.modules`` so the dispatcher imports a deterministic mock --
no live network is touched.

Tests dispatch through ``aurora.cli.forge.main`` directly (rather than a
subprocess) so capsys / monkeypatch work without spawning a child.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from aurora.cli.forge import main as forge_main


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _install_factory(monkeypatch, module_name: str, attr: str, factory):
    """Register ``module_name:attr`` -> ``factory`` for ``_resolve_factory``.

    The CLI side resolves env vars of the form ``module:attr`` to a
    zero-arg factory. We synthesise the module here so the env var
    points at a real importable target.
    """
    mod = types.ModuleType(module_name)
    setattr(mod, attr, factory)
    monkeypatch.setitem(sys.modules, module_name, mod)


def _run_cli(argv) -> int:
    """Dispatch the CLI in-process and propagate the exit code.

    ``forge_main`` returns the command's exit code (or None for argparse
    errors via parser.error -> SystemExit). We wrap SystemExit so tests
    can assert on the integer return.
    """
    try:
        return int(forge_main(argv) or 0)
    except SystemExit as e:
        return int(e.code or 0)


# ---------------------------------------------------------------------------
# 1. identity map (OpenFIGI).
# ---------------------------------------------------------------------------


def test_identity_map_with_mocked_openfigi_returns_table_output(
    monkeypatch, capsys,
):
    """Mocked OpenFIGI returns one mapping row; table output renders it."""

    def http_post(url, payload, headers):
        # OpenFIGI returns one result-dict per submitted job.
        assert payload[0]["idType"] == "TICKER"
        assert payload[0]["idValue"] == "AAPL"
        return [
            {
                "data": [
                    {
                        "figi": "BBG000B9XRY4",
                        "name": "APPLE INC",
                        "ticker": "AAPL",
                        "exchCode": "US",
                        "marketSector": "Equity",
                        "securityType": "Common Stock",
                    }
                ]
            }
        ]

    _install_factory(
        monkeypatch, "_aurora_test_openfigi_factory", "make",
        lambda: http_post,
    )
    monkeypatch.setenv(
        "AU_OPENFIGI_HTTP_POST_FACTORY",
        "_aurora_test_openfigi_factory:make",
    )

    rc = _run_cli([
        "data", "identity", "map",
        "--source", "openfigi",
        "--symbol", "AAPL",
        "--exchange", "US",
        "--id-type", "TICKER",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BBG000B9XRY4" in out
    assert "AAPL" in out
    assert "figi" in out  # table header


def test_identity_map_no_match_prints_warning(monkeypatch, capsys):
    """OpenFIGI 'no match' emits a stderr warning and exits 0 cleanly."""

    def http_post(url, payload, headers):
        return [{"warning": "no FIGI match"}]

    _install_factory(
        monkeypatch, "_aurora_test_openfigi_factory_nomatch", "make",
        lambda: http_post,
    )
    monkeypatch.setenv(
        "AU_OPENFIGI_HTTP_POST_FACTORY",
        "_aurora_test_openfigi_factory_nomatch:make",
    )

    rc = _run_cli([
        "data", "identity", "map",
        "--symbol", "ZZZNOTREAL",
    ])
    assert rc == 0
    cap = capsys.readouterr()
    assert "no FIGI match" in cap.err


def test_identity_map_without_factory_surfaces_gate_message(
    monkeypatch, capsys,
):
    """No injected http_post -> gate RuntimeError -> stderr hint + exit 1."""

    monkeypatch.delenv("AU_OPENFIGI_HTTP_POST_FACTORY", raising=False)

    rc = _run_cli([
        "data", "identity", "map",
        "--symbol", "AAPL",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "OpenFIGI" in err
    assert "http_post" in err


# ---------------------------------------------------------------------------
# 2. fundamentals fetch (SEC EDGAR).
# ---------------------------------------------------------------------------


_FAKE_FACTS_PAYLOAD = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "val": 100.0,
                            "start": "2024-01-01",
                            "end": "2024-03-31",
                            "frame": "CY2024Q1",
                            "accn": "0000320193-24-000001",
                            "filed": "2024-04-01",
                            "accepted": "2024-04-01T16:00:00Z",
                            "form": "10-Q",
                        },
                        {
                            "val": 200.0,
                            "start": "2024-04-01",
                            "end": "2024-06-30",
                            "frame": "CY2024Q2",
                            "accn": "0000320193-24-000002",
                            "filed": "2024-07-15",
                            "accepted": "2024-07-15T16:00:00Z",
                            "form": "10-Q",
                        },
                    ]
                }
            }
        }
    },
}


_FAKE_SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-24-000001",
                "0000320193-24-000002",
            ],
            "filingDate": ["2024-04-01", "2024-07-15"],
            "acceptanceDateTime": [
                "2024-04-01T16:00:00.000Z",
                "2024-07-15T16:00:00.000Z",
            ],
            "form": ["10-Q", "10-Q"],
            "primaryDocument": ["q1.htm", "q2.htm"],
            "periodOfReport": ["2024-03-31", "2024-06-30"],
            "isXBRL": [1, 1],
        }
    }
}


def _fake_sec_http_get(url, headers):
    """Route SEC URLs to local payloads; bytes back like real urllib."""
    if "submissions" in url:
        return json.dumps(_FAKE_SUBMISSIONS_PAYLOAD).encode("utf-8")
    if "companyfacts" in url:
        return json.dumps(_FAKE_FACTS_PAYLOAD).encode("utf-8")
    raise AssertionError(f"unexpected SEC URL: {url}")


def test_fundamentals_fetch_blocks_post_decision_date_facts(
    monkeypatch, capsys,
):
    """A decision-date filter drops facts accepted after the cut-off."""

    _install_factory(
        monkeypatch, "_aurora_test_sec_factory", "make",
        lambda: _fake_sec_http_get,
    )
    monkeypatch.setenv(
        "AU_SEC_EDGAR_HTTP_GET_FACTORY",
        "_aurora_test_sec_factory:make",
    )
    monkeypatch.setenv(
        "AU_SEC_EDGAR_USER_AGENT", "Aurora Test test@example.com",
    )

    rc = _run_cli([
        "data", "fundamentals", "fetch",
        "--source", "sec-edgar",
        "--cik", "320193",
        "--decision-date", "2024-05-01",
        "--output", "json",
    ])
    assert rc == 0
    cap = capsys.readouterr()
    rows = json.loads(cap.out)
    # Only the Q1 fact (accepted 2024-04-01) should survive the
    # 2024-05-01 cut-off; the Q2 fact (accepted 2024-07-15) is dropped.
    assert len(rows) == 1
    assert rows[0]["accepted_iso"].startswith("2024-04-01")
    assert "PIT filter" in cap.err


def test_fundamentals_fetch_without_user_agent_surfaces_gate(
    monkeypatch, capsys,
):
    """Missing User-Agent env var => SECEdgarClient raises gate => exit 1."""

    monkeypatch.delenv("AU_SEC_EDGAR_USER_AGENT", raising=False)
    monkeypatch.delenv("AU_SEC_EDGAR_HTTP_GET_FACTORY", raising=False)

    rc = _run_cli([
        "data", "fundamentals", "fetch",
        "--cik", "320193",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "User-Agent" in err


# ---------------------------------------------------------------------------
# 3. macro search / fetch (DBnomics, ECB).
# ---------------------------------------------------------------------------


def test_macro_search_dbnomics_returns_results(monkeypatch, capsys):
    """DBnomics search returns four-tuple rows; table renders them."""

    def http_get(url, params=None):
        assert url.endswith("/search")
        assert params["q"] == "inflation"
        return json.dumps({
            "results": {
                "docs": [
                    {
                        "provider_code": "ECB",
                        "dataset_code": "ICP",
                        "series_code": "M.U2.N.000000.4.ANR",
                        "name": "Euro area HICP all-items",
                    }
                ]
            }
        })

    _install_factory(
        monkeypatch, "_aurora_test_dbnomics_factory", "make",
        lambda: http_get,
    )
    monkeypatch.setenv(
        "AU_DBNOMICS_HTTP_GET_FACTORY",
        "_aurora_test_dbnomics_factory:make",
    )

    rc = _run_cli([
        "data", "macro", "search",
        "--source", "dbnomics",
        "--query", "inflation",
        "--max-results", "5",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ECB" in out
    assert "ICP" in out
    assert "M.U2.N.000000.4.ANR" in out


def test_macro_fetch_ecb_returns_observations(monkeypatch, capsys):
    """ECB SDMX-JSON parser returns dated observations through the CLI."""

    def http_get(url, params=None, headers=None):
        # SDMX-JSON minimal envelope with one daily observation.
        return json.dumps({
            "header": {},
            "dataSets": [{
                "series": {
                    "0:0:0:0:0": {
                        "observations": {"0": [1.0921]},
                    }
                }
            }],
            "structure": {
                "name": "Daily EUR FX reference rate",
                "dimensions": {
                    "observation": [{
                        "id": "TIME_PERIOD",
                        "values": [{"id": "2024-01-02"}],
                    }]
                },
                "attributes": {"observation": [], "series": []},
            },
        })

    _install_factory(
        monkeypatch, "_aurora_test_ecb_factory", "make",
        lambda: http_get,
    )
    monkeypatch.setenv(
        "AU_ECB_HTTP_GET_FACTORY",
        "_aurora_test_ecb_factory:make",
    )

    rc = _run_cli([
        "data", "macro", "fetch",
        "--source", "ecb",
        "--series", "EXR/D.USD.EUR.SP00.A",
        "--output", "json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert len(rows) == 1
    assert rows[0]["period_iso"] == "2024-01-02"
    assert abs(float(rows[0]["value"]) - 1.0921) < 1e-9


# ---------------------------------------------------------------------------
# 4. crypto-metrics fetch (Coin Metrics community).
# ---------------------------------------------------------------------------


def test_crypto_metrics_fetch_carries_community_warning(
    monkeypatch, capsys,
):
    """Community licence warning lands on stderr; rows render to stdout."""

    def http_get(url):
        # Coin Metrics returns a JSON envelope with a 'data' list.
        return {
            "data": [
                {
                    "asset": "btc",
                    "time": "2024-01-01T00:00:00.000Z",
                    "AdrActCnt": "950000",
                }
            ]
        }

    _install_factory(
        monkeypatch, "_aurora_test_coinmetrics_factory", "make",
        lambda: http_get,
    )
    monkeypatch.setenv(
        "AU_COINMETRICS_HTTP_GET_FACTORY",
        "_aurora_test_coinmetrics_factory:make",
    )
    # Make sure the operator override is NOT set so the warning fires.
    monkeypatch.delenv("AU_COINMETRICS_LICENCE_OVERRIDE", raising=False)

    rc = _run_cli([
        "data", "crypto-metrics", "fetch",
        "--source", "coinmetrics",
        "--asset", "btc",
        "--metric", "AdrActCnt",
    ])
    assert rc == 0
    cap = capsys.readouterr()
    assert "btc" in cap.out
    assert "AdrActCnt" in cap.out
    assert "950000" in cap.out
    assert "community_non_commercial_licence" in cap.err


# ---------------------------------------------------------------------------
# 5. provider-status -- back-compat default vs --include-complementary.
# ---------------------------------------------------------------------------


def test_provider_status_default_excludes_r156(monkeypatch, capsys):
    """Default provider-status omits R156 complementary roles."""

    rc = _run_cli(["data", "provider-status"])
    assert rc == 0
    out = capsys.readouterr().out
    # Baseline R155 providers should be present.
    assert any(t in out for t in ("stooq_daily", "fred_macro", "binance_public_data"))
    # R156 roles should NOT appear by default.
    assert "IDENTITY_MAPPING" not in out
    assert "FUNDAMENTALS" not in out
    assert "MACRO_MULTI_SOURCE" not in out
    assert "CRYPTO_METRICS" not in out
    assert "FX_REFERENCE" not in out


def test_provider_status_include_complementary_lists_r156(
    monkeypatch, capsys,
):
    """``--include-complementary`` surfaces R156 providers."""

    rc = _run_cli([
        "data", "provider-status", "--include-complementary",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # OpenFIGI / DBnomics / ECB / Coin Metrics are unconditionally
    # registered; their R156 roles must appear.
    assert "IDENTITY_MAPPING" in out
    assert "MACRO_MULTI_SOURCE" in out
    assert "CRYPTO_METRICS" in out
    assert "FX_REFERENCE" in out
