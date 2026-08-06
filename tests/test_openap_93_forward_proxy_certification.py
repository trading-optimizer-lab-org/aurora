from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_93.forward_proxy_validation import (
    ForwardProxyCertificate,
    ForwardProxyGate,
    certify_forward_proxy_candidates,
    formula_identity_sha256,
    formula_hashes_from_source_manifest,
)
from aurora.research.openap_93.current_pipeline import (
    apply_forward_proxy_certificates_to_signals,
)
from aurora.research.openap_93.official_portfolio_similarity import build_proxy_spreads


def _certification_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    months = pd.date_range("2005-01-01", "2023-12-01", freq="MS")
    official_values = np.where(np.arange(len(months)) % 2 == 0, 0.02, -0.01)
    official = pd.DataFrame(
        {
            "signal": "DivSeason",
            "month": months,
            "official_return": official_values,
        }
    )
    rows: list[dict[str, object]] = []
    for month, official_return in zip(months, official_values, strict=True):
        if month <= pd.Timestamp("2010-12-01"):
            train_winner = official_return
            validation_winner = -official_return + 0.001
        elif month <= pd.Timestamp("2020-12-01"):
            train_winner = official_return * 0.50
            validation_winner = official_return
        else:
            train_winner = -99.0
            validation_winner = 99.0
        rows.extend(
            [
                {
                    "signal": "DivSeason",
                    "variant_id": "train_winner",
                    "month": month,
                    "proxy_return": train_winner,
                },
                {
                    "signal": "DivSeason",
                    "variant_id": "validation_winner",
                    "month": month,
                    "proxy_return": validation_winner,
                },
            ]
        )
    return pd.DataFrame(rows), official


def test_certification_freezes_train_variant_before_validation() -> None:
    candidates, official = _certification_fixture()

    selected, validation, certificates = certify_forward_proxy_candidates(
        candidates,
        official,
        formula_hashes={
            ("DivSeason", "train_winner"): "formula-train",
            ("DivSeason", "validation_winner"): "formula-validation",
        },
        source_manifest_hashes={
            ("DivSeason", "train_winner"): "source-train",
            ("DivSeason", "validation_winner"): "source-validation",
        },
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        gate=ForwardProxyGate(minimum_common_months=60),
    )

    assert selected.iloc[0]["variant_id"] == "train_winner"
    assert validation.iloc[0]["variant_id"] == "train_winner"
    assert certificates[0].variant_id == "train_winner"
    assert certificates[0].validation_used_for_selection is False
    assert certificates[0].locked_opened is False
    assert certificates[0].backtest_enabled is False


def test_post_2020_mutation_cannot_change_selection_or_certificate() -> None:
    candidates, official = _certification_fixture()
    kwargs = {
        "formula_hashes": {
            ("DivSeason", "train_winner"): "formula-train",
            ("DivSeason", "validation_winner"): "formula-validation",
        },
        "source_manifest_hashes": {
            ("DivSeason", "train_winner"): "source-train",
            ("DivSeason", "validation_winner"): "source-validation",
        },
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "gate": ForwardProxyGate(minimum_common_months=60),
    }
    baseline = certify_forward_proxy_candidates(candidates, official, **kwargs)

    mutated_candidates = candidates.copy()
    locked = pd.to_datetime(mutated_candidates["month"]).gt("2020-12-31")
    mutated_candidates.loc[locked, "proxy_return"] *= -12345.0
    mutated_official = official.copy()
    locked_official = pd.to_datetime(mutated_official["month"]).gt("2020-12-31")
    mutated_official.loc[locked_official, "official_return"] += 777.0
    mutated = certify_forward_proxy_candidates(
        mutated_candidates,
        mutated_official,
        **kwargs,
    )

    baseline_bytes = json.dumps(
        {
            "selected": baseline[0].to_dict("records"),
            "validation": baseline[1].to_dict("records"),
            "certificates": [asdict(item) for item in baseline[2]],
        },
        sort_keys=True,
        default=str,
    ).encode()
    mutated_bytes = json.dumps(
        {
            "selected": mutated[0].to_dict("records"),
            "validation": mutated[1].to_dict("records"),
            "certificates": [asdict(item) for item in mutated[2]],
        },
        sort_keys=True,
        default=str,
    ).encode()
    assert baseline_bytes == mutated_bytes


def test_proxy_spreads_keep_formula_variants_separate() -> None:
    proxy = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"] * 2,
            "formation_month": pd.to_datetime(["2020-02-01"] * 8),
            "signal": ["DivSeason"] * 8,
            "variant_id": ["v1"] * 4 + ["v2"] * 4,
            "proxy_value": [1.0, 2.0, 9.0, 10.0, 10.0, 9.0, 2.0, 1.0],
        }
    )
    monthly = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "completed_month": pd.to_datetime(["2020-02-01"] * 4),
            "month_return": [0.01, 0.02, 0.08, 0.10],
        }
    )

    spreads = build_proxy_spreads(proxy, monthly)

    assert set(spreads["variant_id"]) == {"v1", "v2"}
    by_variant = spreads.set_index("variant_id")["proxy_spread_return"]
    assert by_variant["v1"] == pytest.approx(0.09)
    assert by_variant["v2"] == pytest.approx(-0.09)


def _passing_certificate(
    *,
    formula_sha256: str,
    source_manifest_sha256: str,
) -> ForwardProxyCertificate:
    return ForwardProxyCertificate(
        signal="DivSeason",
        variant_id="formula-v1",
        formula_sha256=formula_sha256,
        source_manifest_sha256=source_manifest_sha256,
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        common_months=120,
        pearson=0.90,
        spearman=0.91,
        sign_agreement=0.80,
        tracking_error=0.01,
        passed=True,
        locked_opened=False,
        validation_used_for_selection=False,
        backtest_enabled=False,
        gate_version="openap-forward-proxy-v1",
    )


def test_current_signal_is_usable_only_with_matching_certificate_identity() -> None:
    formula_hash = formula_identity_sha256("formula-v1")
    source_hash = "source-manifest-v1"
    signals = pd.DataFrame(
        {
            "signal": ["DivSeason", "AnnouncementReturn", "MomVol"],
            "variant_id": ["formula-v1", "formula-v1", "ordinary-formula"],
            "formula_id": ["formula-v1", "formula-v1", "ordinary-formula"],
            "current_usable": [True, True, True],
        }
    )

    result = apply_forward_proxy_certificates_to_signals(
        signals,
        [_passing_certificate(
            formula_sha256=formula_hash,
            source_manifest_sha256=source_hash,
        )],
        source_manifest_sha256=source_hash,
    ).set_index("signal")

    assert bool(result.loc["DivSeason", "current_usable"])
    assert result.loc["DivSeason", "certificate_status"] == "certified"
    assert not bool(result.loc["AnnouncementReturn", "current_usable"])
    assert result.loc["AnnouncementReturn", "certificate_status"] == "missing_certificate"
    assert result.loc["AnnouncementReturn", "effective_score_weight"] == 0.0
    assert bool(result.loc["MomVol", "current_usable"])
    assert result.loc["MomVol", "certificate_status"] == "not_required"


def test_mismatched_formula_or_source_certificate_fails_closed() -> None:
    signals = pd.DataFrame(
        {
            "signal": ["DivSeason"],
            "variant_id": ["formula-v1"],
            "formula_id": ["formula-v1"],
            "current_usable": [True],
        }
    )
    certificate = _passing_certificate(
        formula_sha256=formula_identity_sha256("different-formula"),
        source_manifest_sha256="different-source",
    )

    result = apply_forward_proxy_certificates_to_signals(
        signals,
        [certificate],
        source_manifest_sha256="current-source",
    ).iloc[0]

    assert not bool(result["current_usable"])
    assert result["certificate_status"] == "certificate_identity_mismatch"
    assert result["effective_score_weight"] == 0.0


def test_formula_hash_changes_when_implementation_file_changes(tmp_path: Path) -> None:
    implementation = tmp_path / "formula.py"
    implementation.write_text("VALUE = 1\n", encoding="utf-8")
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(
        "signals:\n"
        "  DivSeason:\n"
        "    formula_id: formula-v1\n"
        "    code: [formula.py]\n",
        encoding="utf-8",
    )
    before = formula_hashes_from_source_manifest(
        manifest, repository_root=tmp_path
    )["DivSeason"]

    implementation.write_text("VALUE = 2\n", encoding="utf-8")
    after = formula_hashes_from_source_manifest(
        manifest, repository_root=tmp_path
    )["DivSeason"]

    assert before != after
