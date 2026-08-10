from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.acquisition_149 import (
    build_acquisition_matrix,
    load_target_routes,
)
from aurora.research.openap_181.recovered_openap93_proxies import (
    COMPEQUISS_FORMULA_ID,
    COMPEQUISS_RECOVERY_SOURCE,
    EQUITY_DURATION_FORMULA_ID,
    EQUITY_DURATION_RECOVERY_SOURCE,
    OPENAP93_RECOVERY_RUN_URL,
    load_verified_openap93_comp_equ_iss,
    load_verified_openap93_proxy_batch,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTE_MATRIX = (
    ROOT / "docs" / "OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"
)
SOURCE_RUN_ID = 31333714423
SOURCE_HEAD_SHA = "34464d5327598282aa2af1523422105dfd5dd184"
OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"


def _row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "ticker": ticker,
        "cik": cik,
        "signal": "CompEquIss",
        "formation_at": "2026-08-09",
        "period_end": "2026-02-28",
        "filed_at": "2026-08-07 00:00:00",
        "available_at": "2026-08-07 00:00:00",
        "retrieved_at": "2026-08-09T22:37:41.271512+00:00",
        "value": value,
        "fidelity_class": "reconstructed" if current_usable else "unavailable",
        "current_usable": current_usable,
        "source_id": "sec_edgar|yahoo_public",
        "source_url": (
            "https://www.sec.gov/files/company_tickers_exchange.json|"
            "https://query1.finance.yahoo.com/v8/finance/chart/AAA"
        ),
        "coverage_flag": "current_usable" if current_usable else "missing",
        "formula_id": COMPEQUISS_FORMULA_ID,
        "openap_script": "Signals/pyCode/Predictors/CompEquIss.py",
        "natural_frequency": "annual",
        "staleness_days": 2.0,
        "is_current_for_natural_frequency": current_usable,
        "observation_count": 85,
        "reason_if_missing": "" if current_usable else "missing_causal_multiyear_inputs",
        "caveat": (
            "Primary-share price times SEC issuer shares replaces CRSP company "
            "market equity"
        ),
    }


def _equity_duration_row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": "EquityDuration",
        "formula_id": EQUITY_DURATION_FORMULA_ID,
        "openap_script": "Signals/pyCode/Predictors/EquityDuration.py",
        "observation_count": 5,
        "caveat": (
            "SEC annual equity/income/revenue and Yahoo fiscal-period price "
            "replace Compustat/CRSP"
        ),
    }


def _write_artifact(root: Path) -> tuple[Path, Path, Path, Path]:
    root.mkdir()
    selected_signals = ["CompEquIss", "EquityDuration"] + [
        f"SyntheticSignal{index:02d}" for index in range(91)
    ]
    comp_rows = [
        _row("US-SEC-0000000001-AAA", "AAA", 1, value=0.25, current_usable=True),
        _row("US-SEC-0000000002-BBB", "BBB", 2, value=-0.10, current_usable=True),
        _row("US-SEC-0000000003-CCC", "CCC", 3, value=None, current_usable=False),
    ]
    equity_duration_rows = [
        _equity_duration_row(
            "US-SEC-0000000001-AAA",
            "AAA",
            1,
            value=16.0,
            current_usable=True,
        ),
        _equity_duration_row(
            "US-SEC-0000000002-BBB",
            "BBB",
            2,
            value=18.0,
            current_usable=True,
        ),
        {
            **_equity_duration_row(
                "US-SEC-0000000003-CCC",
                "CCC",
                3,
                value=None,
                current_usable=False,
            ),
            "period_end": "2026-08-08",
        },
    ]
    filler_rows = [
        {
            **_row(
                f"US-SEC-{index + 10:010d}-ZZZ",
                "ZZZ",
                index + 10,
                value=None,
                current_usable=False,
            ),
            "signal": signal,
            "formula_id": f"synthetic_{index}",
            "openap_script": f"Signals/pyCode/Predictors/{signal}.py",
        }
        for index, signal in enumerate(selected_signals[2:])
    ]
    signals_path = root / "signals_93_current.csv"
    pd.DataFrame(comp_rows + equity_duration_rows + filler_rows).to_csv(
        signals_path,
        index=False,
    )

    coverage_rows = [
        {
            "signal": "CompEquIss",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "sec_edgar",
            "fallback_source": "yahoo_public",
            "source_domains": "query1.finance.yahoo.com|sec.gov",
            "latest_period_end": "2026-02-28",
            "latest_available_at": "2026-08-07 00:00:00",
            "natural_frequency": "annual",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": "Public endpoint; terms must be reviewed|US government public data",
            "terms_status": "authorized_public_rate_limited|terms_review_required",
            "scraping_required": False,
            "reason_if_missing": "missing_causal_multiyear_inputs",
            "openap_script": "Signals/pyCode/Predictors/CompEquIss.py",
            "implementation_file": "research/openap_93/advanced_accounting_pipeline.py",
        }
    ]
    coverage_rows.append(
        {
            "signal": "EquityDuration",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "sec_edgar",
            "fallback_source": "yahoo_public",
            "source_domains": "query1.finance.yahoo.com|sec.gov",
            "latest_period_end": "2026-02-28",
            "latest_available_at": "2026-08-07 00:00:00",
            "natural_frequency": "annual",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": (
                "Public endpoint; terms must be reviewed|US government public data"
            ),
            "terms_status": (
                "authorized_public_rate_limited|terms_review_required"
            ),
            "scraping_required": False,
            "reason_if_missing": "missing_causal_multiyear_inputs",
            "openap_script": "Signals/pyCode/Predictors/EquityDuration.py",
            "implementation_file": (
                "research/openap_93/advanced_accounting_pipeline.py"
            ),
        }
    )
    coverage_rows.extend(
        {
            "signal": signal,
            "status": "unavailable",
            "fidelity_class": "unavailable",
            "current_usable": False,
            "exact_formula": False,
            "primary_source": "",
            "fallback_source": "",
            "source_domains": "",
            "latest_period_end": "",
            "latest_available_at": "",
            "natural_frequency": "annual",
            "universe_count": 1,
            "applicable_count": 1,
            "non_null_count": 0,
            "current_usable_count": 0,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 0,
            "license": "",
            "terms_status": "",
            "scraping_required": False,
            "reason_if_missing": "synthetic",
            "openap_script": f"Signals/pyCode/Predictors/{signal}.py",
            "implementation_file": "synthetic.py",
        }
        for signal in selected_signals[2:]
    )
    coverage_path = root / "coverage_93.csv"
    pd.DataFrame(coverage_rows).to_csv(coverage_path, index=False)

    source_manifest_path = root / "source_run_manifest.json"
    source_manifest = {
        "formation_at": "2026-08-09T00:00:00",
        "retrieved_at": "2026-08-09T22:37:41.271512+00:00",
        "input_signals": 93,
        "universe_count": 3,
        "rows": len(comp_rows) + len(equity_duration_rows) + len(filler_rows),
        "openap_commit": OPENAP_COMMIT,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "api_keys_required": False,
        "manual_actions_required": False,
        "selected_signals": selected_signals,
        "current_usable_signal_count": 2,
        "output_hashes": {
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
        },
    }
    source_manifest_path.write_text(
        json.dumps(source_manifest, sort_keys=True), encoding="utf-8"
    )

    recovery_manifest_path = root / "openap_93_artifact_recovery_manifest.json"
    recovery_manifest = {
        "bytes_fetched": 13720277,
        "cost_eur": 0,
        "current_usable_signal_count": 2,
        "full_artifact_downloaded": False,
        "input_signals": 93,
        "locked_opened": False,
        "range_requests": 12,
        "source_artifact_id": 9045608652,
        "source_artifact_name": "openap-93-max-free-failed-output-31333714423",
        "source_artifact_size_bytes": 2741147673,
        "source_head_sha": SOURCE_HEAD_SHA,
        "source_run_id": SOURCE_RUN_ID,
        "source_run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
            f"{SOURCE_RUN_ID}"
        ),
        "strict_score_eligible": False,
        "validation_used_for_selection": False,
        "recovered_hashes": {
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "run_manifest.json": sha256(source_manifest_path.read_bytes()).hexdigest(),
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
        },
    }
    recovery_manifest_path.write_text(
        json.dumps(recovery_manifest, sort_keys=True), encoding="utf-8"
    )
    return signals_path, coverage_path, source_manifest_path, recovery_manifest_path


def _rewrite_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _rehash_artifact(
    signals_path: Path,
    coverage_path: Path,
    source_path: Path,
    recovery_path: Path,
) -> None:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["output_hashes"].update(
        {
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
        }
    )
    source_path.write_text(json.dumps(source, sort_keys=True), encoding="utf-8")
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery["recovered_hashes"].update(
        {
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
        }
    )
    recovery_path.write_text(
        json.dumps(recovery, sort_keys=True),
        encoding="utf-8",
    )


def test_verified_openap93_recovery_accepts_only_current_comp_equ_iss(
    tmp_path: Path,
) -> None:
    paths = _write_artifact(tmp_path / "artifact")

    values, evidence_paths, evidence = load_verified_openap93_comp_equ_iss(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )

    assert len(values) == 2
    assert set(values["ticker"]) == {"AAA", "BBB"}
    assert values["current_usable"].all()
    assert not values["strict_score_eligible"].any()
    assert values["fidelity_class"].eq("reconstructed").all()
    assert values["source_id"].eq(COMPEQUISS_RECOVERY_SOURCE).all()
    assert values["formula_id"].eq(COMPEQUISS_FORMULA_ID).all()
    assert values["caveat"].str.contains("historical CRSP identity not verified").all()
    assert set(evidence_paths) == set(paths)
    assert evidence["source_run_id"] == SOURCE_RUN_ID
    assert evidence["current_value_rows"] == 2
    assert evidence["strict_score_increment"] == 0


def test_verified_openap93_proxy_batch_adds_low_coverage_equity_duration(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")

    values, _, evidence = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )

    assert values.groupby("signal").size().to_dict() == {
        "CompEquIss": 2,
        "EquityDuration": 2,
    }
    duration = values.loc[values["signal"].eq("EquityDuration")]
    assert duration["source_id"].eq(EQUITY_DURATION_RECOVERY_SOURCE).all()
    assert duration["formula_id"].eq(EQUITY_DURATION_FORMULA_ID).all()
    assert duration["fidelity_class"].eq("reconstructed").all()
    assert duration["caveat"].str.contains(
        "historical Compustat/CRSP identity not verified"
    ).all()
    assert not duration["strict_score_eligible"].any()
    assert evidence["signals"]["EquityDuration"]["current_value_rows"] == 2
    assert evidence["strict_score_increment"] == 0


@pytest.mark.parametrize(
    "mutation",
    ["formula", "source", "caveat", "observations", "coverage_count"],
)
def test_verified_equity_duration_recovery_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    signals_path, coverage_path, source_path, recovery_path = _write_artifact(
        tmp_path / "artifact"
    )
    if mutation == "coverage_count":
        coverage = pd.read_csv(coverage_path)
        coverage.loc[
            coverage["signal"].eq("EquityDuration"),
            "current_usable_count",
        ] = 3
        coverage.to_csv(coverage_path, index=False)
    else:
        values = pd.read_csv(signals_path)
        row = values.index[
            values["signal"].eq("EquityDuration")
            & values["current_usable"].astype(str).str.lower().eq("true")
        ][0]
        if mutation == "formula":
            values.loc[row, "formula_id"] = "wrong_formula"
        elif mutation == "source":
            values.loc[row, "source_id"] = "sec_edgar"
        elif mutation == "caveat":
            values.loc[row, "caveat"] = "weaker undocumented proxy"
        else:
            values.loc[row, "observation_count"] = 1
        values.to_csv(signals_path, index=False)
    _rehash_artifact(signals_path, coverage_path, source_path, recovery_path)

    with pytest.raises(ValueError):
        load_verified_openap93_proxy_batch(
            tmp_path / "artifact",
            evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "recovery_hash",
        "source_hash",
        "formula",
        "source",
        "duplicate_identity",
        "lookahead",
        "coverage_count",
        "artifact_identity",
        "strict_manifest",
        "source_safety",
    ],
)
def test_verified_openap93_recovery_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    signals_path, coverage_path, source_path, recovery_path = _write_artifact(
        tmp_path / "artifact"
    )
    if mutation == "recovery_hash":
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "signals_93_current.csv", "0" * 64
            ),
        )
    elif mutation == "source_hash":
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "signals_93_current.csv", "0" * 64
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "run_manifest.json", sha256(source_path.read_bytes()).hexdigest()
            ),
        )
    elif mutation in {"formula", "source", "duplicate_identity", "lookahead"}:
        frame = pd.read_csv(signals_path)
        comp = frame.index[frame["signal"].eq("CompEquIss")]
        if mutation == "formula":
            frame.loc[comp[0], "formula_id"] = "wrong_formula"
        elif mutation == "source":
            frame.loc[comp[0], "source_id"] = "yahoo_public"
        elif mutation == "duplicate_identity":
            frame.loc[comp[1], "security_id"] = frame.loc[comp[0], "security_id"]
        else:
            frame.loc[comp[0], "available_at"] = "2026-08-10 00:00:00"
        frame.to_csv(signals_path, index=False)
        digest = sha256(signals_path.read_bytes()).hexdigest()
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "signals_93_current.csv", digest
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].update(
                {
                    "signals_93_current.csv": digest,
                    "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
                }
            ),
        )
    elif mutation == "coverage_count":
        frame = pd.read_csv(coverage_path)
        frame.loc[frame["signal"].eq("CompEquIss"), "current_usable_count"] = 3
        frame.to_csv(coverage_path, index=False)
        digest = sha256(coverage_path.read_bytes()).hexdigest()
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "coverage_93.csv", digest
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].update(
                {
                    "coverage_93.csv": digest,
                    "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
                }
            ),
        )
    elif mutation == "artifact_identity":
        _rewrite_json(
            recovery_path,
            lambda payload: payload.__setitem__(
                "source_artifact_size_bytes", 2741147672
            ),
        )
    elif mutation == "strict_manifest":
        _rewrite_json(
            recovery_path,
            lambda payload: payload.__setitem__("strict_score_eligible", True),
        )
    else:
        _rewrite_json(
            source_path,
            lambda payload: payload.__setitem__("locked_opened", True),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "run_manifest.json", sha256(source_path.read_bytes()).hexdigest()
            ),
        )

    with pytest.raises(ValueError):
        load_verified_openap93_comp_equ_iss(
            tmp_path / "artifact",
            evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
        )


def test_comp_equ_iss_recovery_route_is_narrow_and_non_strict(tmp_path: Path) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, _ = load_verified_openap93_comp_equ_iss(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    routes = load_target_routes(ROUTE_MATRIX)
    route = routes.loc[routes["signal"].eq("CompEquIss")].iloc[0]
    assert COMPEQUISS_RECOVERY_SOURCE in route["primary_free_sources"].split("|")
    assert "yahoo_public" not in route["primary_free_sources"].split("|")

    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {
                    "signal": "CompEquIss",
                    "formula_sha256": (
                        "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b"
                    ),
                }
            ]
        ),
    )
    comp = matrix.loc[matrix["signal"].eq("CompEquIss")].iloc[0]
    assert comp["status"] == "current_signal_computed"
    assert comp["current_value_count"] == 2
    assert comp["fidelity"] == "reconstructed"
    assert not bool(comp["strict_score_eligible"])
    assert set(approved["signal"]) == {"CompEquIss"}


def test_equity_duration_recovery_route_is_narrow_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, _ = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    routes = load_target_routes(ROUTE_MATRIX)
    route = routes.loc[routes["signal"].eq("EquityDuration")].iloc[0]
    assert EQUITY_DURATION_RECOVERY_SOURCE in route["primary_free_sources"].split(
        "|"
    )
    assert "yahoo_public" not in route["primary_free_sources"].split("|")

    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {
                    "signal": "CompEquIss",
                    "formula_sha256": (
                        "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b"
                    ),
                },
                {
                    "signal": "EquityDuration",
                    "formula_sha256": (
                        "3e4adc868044a3de5b420a8555f816557a8d02dfa3112a09f114bff4593a9997"
                    ),
                },
            ]
        ),
    )
    duration = matrix.loc[matrix["signal"].eq("EquityDuration")].iloc[0]
    assert duration["status"] == "current_signal_computed"
    assert duration["current_value_count"] == 2
    assert duration["coverage"] == pytest.approx(2 / 3)
    assert duration["fidelity"] == "reconstructed"
    assert not bool(duration["strict_score_eligible"])
    assert set(approved["signal"]) == {"CompEquIss", "EquityDuration"}
