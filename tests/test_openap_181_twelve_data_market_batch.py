from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from importlib import util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]

from aurora.research.openap_181.implementation_status import (
    TWELVE_DATA_MARKET_SIGNALS as FROZEN_MARKET_SIGNALS,
)
from aurora.research.openap_181.twelve_data_market_batch import (
    ADJUSTMENT_MODES,
    API_KEY_ENV,
    MAX_CREDITS_PER_DAY,
    MAX_CREDITS_PER_MINUTE,
    MINIMUM_HISTORY_MONTHS,
    TwelveDataClient,
    TwelveDataIdentityError,
    TwelveDataSourceError,
    build_twelve_data_request_plan,
    completed_request_ids,
    estimate_twelve_data_quota,
    prepare_twelve_data_universe,
    redact_twelve_data_secret,
)


def _security_master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "symbol": "AAPL",
                "cik": 320193,
                "exchange_sec": "Nasdaq",
                "eligible_common_stock": True,
                "issuer_primary_security": True,
                "issuer_share_class_count": 1,
                "ranking_eligible": True,
                "source_sec": "sec_company_tickers_exchange",
                "retrieved_at_sec": "2026-08-07T20:06:32Z",
            },
            {
                "security_id": "US-SEC-0001067983-BRK-B",
                "symbol": "BRK-B",
                "cik": 1067983,
                "exchange_sec": "NYSE",
                "eligible_common_stock": True,
                "issuer_primary_security": True,
                "issuer_share_class_count": 1,
                "ranking_eligible": True,
                "source_sec": "sec_company_tickers_exchange",
                "retrieved_at_sec": "2026-08-07T20:06:32Z",
            },
        ]
    )


def _response_payload(
    *,
    symbol: str = "AAPL",
    exchange: str = "NASDAQ",
    mic_code: str = "XNGS",
    instrument_type: str = "Common Stock",
    exchange_timezone: str = "America/New_York",
) -> bytes:
    return json.dumps(
        {
            "meta": {
                "symbol": symbol,
                "interval": "1day",
                "currency": "USD",
                "exchange_timezone": exchange_timezone,
                "exchange": exchange,
                "mic_code": mic_code,
                "type": instrument_type,
            },
            "values": [
                {
                    "datetime": "2026-08-06",
                    "open": "100.00",
                    "high": "103.00",
                    "low": "99.00",
                    "close": "102.00",
                    "volume": "1000",
                },
                {
                    "datetime": "2026-08-07",
                    "open": "102.00",
                    "high": "104.00",
                    "low": "101.00",
                    "close": "103.00",
                    "volume": "1200",
                },
            ],
            "status": "ok",
        },
        sort_keys=True,
    ).encode("utf-8")


def test_market_batch_is_bound_to_exact_frozen_31_signal_set() -> None:
    assert len(FROZEN_MARKET_SIGNALS) == 31
    assert MINIMUM_HISTORY_MONTHS == 182
    assert ADJUSTMENT_MODES == ("all", "none")
    assert MAX_CREDITS_PER_MINUTE == 8
    assert MAX_CREDITS_PER_DAY == 800


def test_universe_requires_unambiguous_primary_current_sec_identity() -> None:
    frame = pd.concat(
        [
            _security_master(),
            pd.DataFrame(
                [
                    {
                        "security_id": "US-SEC-0000000003-DUP",
                        "symbol": "AAPL",
                        "cik": 3,
                        "exchange_sec": "NYSE",
                        "eligible_common_stock": True,
                        "issuer_primary_security": True,
                        "issuer_share_class_count": 1,
                        "ranking_eligible": True,
                        "source_sec": "sec_company_tickers_exchange",
                        "retrieved_at_sec": "2026-08-07T20:06:32Z",
                    },
                    {
                        "security_id": "US-SEC-0000000004-OTC",
                        "symbol": "OTC",
                        "cik": 4,
                        "exchange_sec": "OTC Markets",
                        "eligible_common_stock": True,
                        "issuer_primary_security": True,
                        "issuer_share_class_count": 1,
                        "ranking_eligible": True,
                        "source_sec": "sec_company_tickers_exchange",
                        "retrieved_at_sec": "2026-08-07T20:06:32Z",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )

    accepted, rejected = prepare_twelve_data_universe(frame)

    assert accepted["ticker"].tolist() == ["BRK-B"]
    assert accepted["provider_symbol"].tolist() == ["BRK.B"]
    assert accepted["cik"].tolist() == ["0001067983"]
    assert accepted["issuer_share_class_count"].tolist() == [1]
    assert accepted["identity_available_at"].tolist() == [
        "2026-08-07T20:06:32+00:00"
    ]
    assert accepted["identity_source_url"].tolist() == [
        "https://www.sec.gov/files/company_tickers_exchange.json"
    ]
    reasons = set(rejected["reason_if_rejected"])
    assert "duplicate_current_ticker" in reasons
    assert "unsupported_or_nonlisted_us_exchange" in reasons
    assert accepted["security_id"].is_unique
    assert accepted["ticker"].is_unique
    assert accepted["cik"].is_unique


def test_universe_rejects_security_id_that_disagrees_with_cik_or_ticker() -> None:
    frame = _security_master().iloc[[0]].copy()
    frame.loc[:, "security_id"] = "US-SEC-0000320193-MSFT"

    accepted, rejected = prepare_twelve_data_universe(frame)

    assert accepted.empty
    assert rejected["reason_if_rejected"].tolist() == [
        "security_id_cik_ticker_mismatch"
    ]


def test_universe_rejects_non_live_or_future_sec_identity_evidence() -> None:
    fallback = _security_master().iloc[[0]].assign(
        source_sec="sec_cik_mapper_pinned_sec_derived"
    )
    invalid_time = _security_master().iloc[[1]].assign(
        retrieved_at_sec="not-a-date"
    )

    accepted, rejected = prepare_twelve_data_universe(
        pd.concat([fallback, invalid_time], ignore_index=True)
    )

    assert accepted.empty
    assert set(rejected["reason_if_rejected"]) == {
        "current_identity_not_from_official_sec_live",
        "missing_current_identity_available_at",
    }


def test_universe_requires_real_post_merge_sec_provenance_columns() -> None:
    impostor = _security_master().drop(
        columns=["source_sec", "retrieved_at_sec"]
    ).assign(
        source="sec_company_tickers_exchange",
        retrieved_at="2026-08-07T20:06:32Z",
    )

    with pytest.raises(ValueError, match="retrieved_at_sec.*source_sec"):
        prepare_twelve_data_universe(impostor)


def test_request_plan_rejects_identity_observed_after_formation() -> None:
    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])

    with pytest.raises(ValueError, match="identity after formation"):
        build_twelve_data_request_plan(
            accepted,
            formation_at="2026-08-06T23:59:59Z",
        )


def test_request_plan_rejects_invalid_formation_timestamp() -> None:
    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])

    with pytest.raises(ValueError, match="formation_at"):
        build_twelve_data_request_plan(accepted, formation_at="not-a-date")


def test_request_plan_uses_two_explicit_adjustments_and_six_free_quota_days() -> None:
    master = pd.concat([_security_master().iloc[[0]]] * 2157, ignore_index=True)
    master["symbol"] = [f"S{index:04d}" for index in range(2157)]
    master["cik"] = range(1, 2158)
    master["security_id"] = [
        f"US-SEC-{index:010d}-S{index - 1:04d}" for index in range(1, 2158)
    ]
    accepted, rejected = prepare_twelve_data_universe(master)
    assert rejected.empty

    plan = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    )
    quota = estimate_twelve_data_quota(plan)

    assert len(plan) == 4314
    assert set(plan["adjust"]) == {"all", "none"}
    assert plan["request_id"].is_unique
    assert plan["safe_url"].str.contains("apikey", case=False).sum() == 0
    assert plan["start_date"].eq("2011-06-09").all()
    assert plan["end_date"].eq("2026-08-09").all()
    assert quota == {
        "requests": 4314,
        "credits": 4314,
        "minimum_quota_days": 6,
        "minimum_rate_limited_minutes": 540,
    }


def test_api_key_is_only_sent_in_authorization_header_and_never_in_url() -> None:
    captured: dict[str, object] = {}

    def http_get(url: str, headers: dict[str, str], timeout: float):
        captured.update(url=url, headers=dict(headers), timeout=timeout)
        return 200, {"Content-Type": "application/json"}, _response_payload()

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]
    client = TwelveDataClient(api_key="secret-key", http_get=http_get)

    result = client.fetch(
        request,
        retrieved_at="2026-08-10T05:30:00Z",
    )

    assert captured["headers"]["Authorization"] == "apikey secret-key"
    assert "secret-key" not in str(captured["url"])
    assert "apikey" not in parse_qs(urlparse(str(captured["url"])).query)
    assert result.safe_url == captured["url"]
    assert result.raw_sha256
    assert result.meta["mic_code"] == "XNGS"
    assert result.bars["available_at_quality"].tolist() == [
        "next_observed_session_midnight_et",
        "retrieval_timestamp_conservative",
    ]
    assert result.bars.loc[0, "available_at"] == "2026-08-07T04:00:00+00:00"
    assert result.bars.loc[1, "available_at"] == "2026-08-10T05:30:00+00:00"


@pytest.mark.parametrize(
    (
        "symbol",
        "exchange",
        "mic_code",
        "instrument_type",
        "exchange_timezone",
    ),
    [
        ("MSFT", "NASDAQ", "XNGS", "Common Stock", "America/New_York"),
        ("AAPL", "NYSE", "XNYS", "Common Stock", "America/New_York"),
        ("AAPL", "NASDAQ", "XNGS", "Preferred Stock", "America/New_York"),
        ("AAPL", "NASDAQ", "XNGS", "Common Stock", "Europe/London"),
    ],
)
def test_response_identity_mismatch_fails_closed(
    symbol: str,
    exchange: str,
    mic_code: str,
    instrument_type: str,
    exchange_timezone: str,
) -> None:
    def http_get(_url: str, _headers: dict[str, str], _timeout: float):
        return 200, {}, _response_payload(
            symbol=symbol,
            exchange=exchange,
            mic_code=mic_code,
            instrument_type=instrument_type,
            exchange_timezone=exchange_timezone,
        )

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]

    with pytest.raises(TwelveDataIdentityError):
        TwelveDataClient(api_key="secret", http_get=http_get).fetch(
            request,
            retrieved_at="2026-08-10T05:30:00Z",
        )


def test_malformed_or_error_response_is_source_failure_without_secret_leak() -> None:
    def http_get(_url: str, _headers: dict[str, str], _timeout: float):
        payload = {
            "code": 429,
            "message": "quota for secret-key exhausted",
            "status": "error",
        }
        return 429, {}, json.dumps(payload).encode("utf-8")

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]

    with pytest.raises(TwelveDataSourceError) as excinfo:
        TwelveDataClient(api_key="secret-key", http_get=http_get).fetch(
            request,
            retrieved_at=datetime.now(UTC),
        )
    assert "secret-key" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
def test_credential_rate_limit_and_server_errors_remain_retryable(
    status_code: int,
) -> None:
    def http_get(_url: str, _headers: dict[str, str], _timeout: float):
        return status_code, {}, json.dumps(
            {"status": "error", "message": "temporary or credential failure"}
        ).encode("utf-8")

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]

    with pytest.raises(TwelveDataSourceError) as excinfo:
        TwelveDataClient(api_key="secret", http_get=http_get).fetch(request)
    assert excinfo.value.retryable is True


def test_transport_failure_is_defined_as_retryable() -> None:
    def http_get(_url: str, _headers: dict[str, str], _timeout: float):
        raise TwelveDataSourceError(
            "Twelve Data transport failure: TimeoutError",
            status_code=0,
            retryable=True,
        )

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]

    with pytest.raises(TwelveDataSourceError) as excinfo:
        TwelveDataClient(api_key="secret", http_get=http_get).fetch(request)
    assert excinfo.value.status_code == 0
    assert excinfo.value.retryable is True


def test_injected_keyless_client_still_enforces_secret_free_url() -> None:
    def http_get(_url: str, _headers: dict[str, str], _timeout: float):
        return 200, {}, _response_payload()

    accepted, _ = prepare_twelve_data_universe(_security_master().iloc[[0]])
    request = build_twelve_data_request_plan(
        accepted,
        formation_at="2026-08-09T23:59:59Z",
    ).iloc[0]

    result = TwelveDataClient(api_key="", http_get=http_get).fetch(
        request,
        retrieved_at="2026-08-10T05:30:00Z",
    )

    assert not result.bars.empty


def test_checkpoint_only_skips_successful_terminal_request_ids(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        "\n".join(
            [
                json.dumps({"request_id": "ok", "status": "success"}),
                json.dumps({"request_id": "bad", "status": "terminal_error"}),
                json.dumps({"request_id": "retry", "status": "retryable_error"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert completed_request_ids(checkpoint) == {"ok", "bad"}


def test_resume_rejects_checkpoint_from_a_different_hashed_plan(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts" / "run_openap_149_twelve_data_market.py"
    spec = util.spec_from_file_location("run_openap_149_twelve_data_market", script)
    assert spec is not None and spec.loader is not None
    runner = util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    output = tmp_path / "output"
    restricted = output / "restricted_internal_raw"
    restricted.mkdir(parents=True)
    normalized = restricted / "ok.parquet"
    normalized.write_bytes(b"normalized-market-row")
    contract = {"contract_version": 1, "implementation_sha": "a" * 40}
    contract_hash = runner._canonical_json_sha256(contract)
    checkpoint = output / "twelve_data_checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(
            {
                "request_id": "ok",
                "status": "success",
                "resume_contract_sha256": contract_hash,
                "restricted_relative_path": "restricted_internal_raw/ok.parquet",
                "normalized_sha256": sha256(normalized.read_bytes()).hexdigest(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    prior_manifest = output / "twelve_data_market_acquisition_manifest.json"
    prior_manifest.write_text(
        json.dumps(
            {
                "resume_contract": contract,
                "resume_contract_sha256": contract_hash,
            }
        ),
        encoding="utf-8",
    )

    assert runner._validate_resume(
        checkpoint,
        restricted,
        {"ok"},
        prior_manifest,
        contract,
        contract_hash,
    ) == {"ok"}

    with pytest.raises(RuntimeError, match="exact plan"):
        runner._validate_resume(
            checkpoint,
            restricted,
            {"ok"},
            prior_manifest,
            {**contract, "implementation_sha": "b" * 40},
            "b" * 64,
        )

    checkpoint.write_text(
        json.dumps(
            {
                "request_id": "foreign",
                "status": "retryable_error",
                "resume_contract_sha256": contract_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="request/status contract"):
        runner._validate_resume(
            checkpoint,
            restricted,
            {"ok"},
            prior_manifest,
            contract,
            contract_hash,
        )


def test_runner_binds_recovered_security_master_and_sec_source_manifest(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts" / "run_openap_149_twelve_data_market.py"
    spec = util.spec_from_file_location("run_openap_149_twelve_data_market", script)
    assert spec is not None and spec.loader is not None
    runner = util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    security_master = tmp_path / "security_master.parquet"
    source_manifest = tmp_path / "source_manifest.csv"
    security_master.write_bytes(b"bound-security-master")
    source_manifest.write_bytes(b"bound-sec-source-manifest")
    recovery = {
        "source_run_id": 31270341796,
        "source_head_sha": "a" * 40,
        "source_artifact_id": 999,
        "source_artifact_name": "openap-yfinance-sec-current-score-results",
        "full_artifact_downloaded": False,
        "identity_input_only": True,
        "identity_source_url": (
            "https://www.sec.gov/files/company_tickers_exchange.json"
        ),
        "identity_source_mode": "sec_official_live",
        "identity_source_sha256": "b" * 64,
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
        "database_contract_violations": 0,
        "eligible_symbols": 2157,
        "security_master_rows": 2200,
        "recovered_hashes": {
            "security_master.parquet": sha256(
                security_master.read_bytes()
            ).hexdigest(),
            "source_manifest.csv": sha256(
                source_manifest.read_bytes()
            ).hexdigest(),
        },
    }
    recovery_path = tmp_path / "recovery.json"
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")

    validated = runner._validate_source_recovery(
        recovery_path,
        security_master,
        source_manifest,
    )

    assert validated["identity_source_mode"] == "sec_official_live"
    recovery_path.write_text(
        json.dumps({**recovery, "source_artifact_id": 999.5}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="recovery contract"):
        runner._validate_source_recovery(
            recovery_path,
            security_master,
            source_manifest,
        )
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    source_manifest.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="recovery contract"):
        runner._validate_source_recovery(
            recovery_path,
            security_master,
            source_manifest,
        )


def test_secret_redaction_covers_header_and_query_forms() -> None:
    value = "Authorization: apikey top-secret apikey=top-secret&symbol=AAPL"
    redacted = redact_twelve_data_secret(value, "top-secret")

    assert "top-secret" not in redacted
    assert API_KEY_ENV not in value
    assert redacted.count("[REDACTED]") >= 1


def test_market_runner_and_workflow_preserve_manual_private_boundaries() -> None:
    runner = (
        ROOT / "scripts" / "run_openap_149_twelve_data_market.py"
    ).read_text(encoding="utf-8")
    recovery = (
        ROOT / "scripts" / "recover_openap_market_security_master.py"
    ).read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-twelve-data-market.yml"
    ).read_text(encoding="utf-8")

    assert "require_github_actions_or_explicit_local_permission" in runner
    assert "--source-recovery-manifest" in runner
    assert "--source-manifest" in runner
    assert "--implementation-sha" in runner
    assert "resume_contract_sha256" in runner
    assert '"historical_ticker_interval_verified": False' in runner
    assert "_calculate_complete_direct_signals" in runner
    assert "calculate_twelve_data_factor_signals" in runner
    assert 'parser.add_argument("--ff3-daily-zip"' in runner
    assert 'parser.add_argument("--ff3-monthly-zip"' in runner
    assert "not direct_values.empty and not factor_values.empty" in runner
    assert '"strict_score_eligible": False' in runner
    assert "MARKET_SECURITY_MASTER_RECOVERY_MEMBERS" in recovery
    assert "full_artifact_downloaded" in recovery
    assert "research/openap_181/sec_listing_identity.py" in workflow
    assert "tests/test_openap_181_sec_listing_identity.py" in workflow
    assert "tests/test_openap_181_twelve_data_market_signals.py" in workflow
    assert "twelve_data_direct_signal_observations.parquet" in workflow
    assert "twelve_data_factor_signal_observations.parquet" in workflow
    assert "restricted_internal_factors" in workflow
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert 'test "${{ github.event.repository.private }}" = "true"' in workflow
    assert "secrets.TWELVE_DATA_API_KEY" in workflow
    assert "resume_run_id" in workflow
    assert "openap-149-twelve-data-market-restricted" in workflow
    publishable_block = workflow.split(
        "Upload publishable acquisition evidence without raw market rows",
        maxsplit=1,
    )[1]
    assert "restricted_internal_raw" not in publishable_block
