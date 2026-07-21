"""Contracts for the single-run frozen causal FX artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.prepare_stock_protocol_290_fx import (
    CUTOFF,
    FX_LOCK_NAME,
    FX_RATES_NAME,
    prepare_fx_artifact,
    verify_fx_artifact,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    audit = tmp_path / "audit"
    exact = tmp_path / "exact"
    audit.mkdir()
    exact.mkdir()
    pd.DataFrame(
        {
            "symbol": ["US", "EU", "UNKNOWN"],
            "currency": ["USD", "EUR", "unknown"],
            "currency_unknown": [False, False, True],
        }
    ).to_csv(audit / "symbol_exchange_currency_map.csv", index=False)
    (audit / "final_artifact_manifest.json").write_text(
        json.dumps({"files": {"symbol_exchange_currency_map.csv": {}}}),
        encoding="utf-8",
    )
    (exact / "final_artifact_manifest.json").write_text(
        json.dumps({"files": {"exact_oos_summary.json": {}}}), encoding="utf-8"
    )
    lock = tmp_path / "stock-protocol-290-source-lock.json"
    lock.write_text(
        json.dumps(
            {
                "cutoff": "2026-07-17",
                "verified_artifacts": [
                    {
                        "role": "prior_opportunity_audit",
                        "run_id": 29804082610,
                        "name": "stock-protocol-all-opportunities-and-realistic-portfolio-audit",
                        "digest": "sha256:" + "a" * 64,
                    },
                    {
                        "role": "frozen_exact_strategy",
                        "run_id": 29688666475,
                        "name": "stock-protocol-exact-irrevocable-oos-results-final",
                        "digest": "sha256:" + "b" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return audit, exact, lock


def test_prepare_fx_artifact_freezes_cutoff_hash_and_source(tmp_path: Path) -> None:
    audit, exact, source_lock = _sources(tmp_path)
    output = tmp_path / "fx"

    def download(symbols: list[str], start: str, end: str) -> dict[str, pd.Series]:
        assert symbols == ["EURUSD=X", "USDEUR=X"]
        assert start == "2006-01-01"
        assert end == "2026-07-18"
        return {
            "EURUSD=X": pd.Series(
                [1.1, 1.2],
                index=pd.to_datetime(["2006-01-03", "2026-07-17"]),
            )
        }

    payload = prepare_fx_artifact(
        audit_root=audit,
        exact_root=exact,
        source_lock_path=source_lock,
        output_root=output,
        downloader=download,
    )

    rates_path = output / FX_RATES_NAME
    lock_path = output / FX_LOCK_NAME
    rates = pd.read_csv(rates_path)
    frozen = json.loads(lock_path.read_text(encoding="utf-8"))
    assert set(rates["currency"]) == {"EUR", "USD"}
    assert pd.to_datetime(rates["date"]).max() == CUTOFF
    assert set(rates["source"]) == {"identity", "Yahoo Finance historical FX"}
    assert frozen["cutoff"] == "2026-07-17"
    assert frozen["rates_file"] == FX_RATES_NAME
    assert frozen["rates_sha256"] == _sha256(rates_path)
    assert frozen["source_provider"] == "Yahoo Finance historical FX via yfinance"
    assert {item["role"] for item in frozen["source_artifacts"]} == {
        "prior_opportunity_audit",
        "frozen_exact_strategy",
    }
    assert payload == frozen
    assert verify_fx_artifact(output) == frozen


def test_prepare_fx_artifact_rejects_missing_known_currency(tmp_path: Path) -> None:
    audit, exact, source_lock = _sources(tmp_path)

    with pytest.raises(ValueError, match="EUR"):
        prepare_fx_artifact(
            audit_root=audit,
            exact_root=exact,
            source_lock_path=source_lock,
            output_root=tmp_path / "fx",
            downloader=lambda symbols, start, end: {},
        )


def test_prepare_fx_artifact_clips_vendor_rows_after_cutoff(tmp_path: Path) -> None:
    audit, exact, source_lock = _sources(tmp_path)

    prepare_fx_artifact(
        audit_root=audit,
        exact_root=exact,
        source_lock_path=source_lock,
        output_root=tmp_path / "fx",
        downloader=lambda symbols, start, end: {
            "EURUSD=X": pd.Series(
                [1.2, 9.9],
                index=pd.to_datetime(["2026-07-17", "2026-07-18"]),
            )
        },
    )

    rates = pd.read_csv(tmp_path / "fx" / FX_RATES_NAME)
    assert pd.to_datetime(rates["date"]).max() <= CUTOFF
    assert 9.9 not in rates["usd_per_local"].tolist()


def test_verify_fx_artifact_rejects_hash_mutation(tmp_path: Path) -> None:
    audit, exact, source_lock = _sources(tmp_path)
    output = tmp_path / "fx"
    prepare_fx_artifact(
        audit_root=audit,
        exact_root=exact,
        source_lock_path=source_lock,
        output_root=output,
        downloader=lambda symbols, start, end: {
            "EURUSD=X": pd.Series(
                [1.2], index=pd.to_datetime(["2026-07-17"])
            )
        },
    )
    with (output / FX_RATES_NAME).open("a", encoding="utf-8") as handle:
        handle.write("2026-07-18,EUR,9.9,tampered,tampered,tampered,2026-07-17\n")

    with pytest.raises(ValueError, match="sha256"):
        verify_fx_artifact(output)
