from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from aurora.research.openap_93.forward_proxy_validation import (
    ForwardProxyGate,
    apply_certificates,
    certificate_sha256,
    select_train_variant,
    validate_frozen_variant,
)


def _monthly_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    months = pd.date_range("2000-01-01", "2020-12-01", freq="MS")
    official_values = np.sin(np.arange(len(months), dtype=float) / 5.0)
    official = pd.DataFrame(
        {
            "signal": "DivSeason",
            "month": months,
            "official_return": official_values,
        }
    )
    candidates = pd.concat(
        [
            pd.DataFrame(
                {
                    "signal": "DivSeason",
                    "variant_id": "faithful",
                    "month": months,
                    "proxy_return": official_values,
                }
            ),
            pd.DataFrame(
                {
                    "signal": "DivSeason",
                    "variant_id": "validation_bait",
                    "month": months,
                    "proxy_return": np.where(
                        months <= pd.Timestamp("2010-12-31"),
                        -official_values,
                        official_values,
                    ),
                }
            ),
        ],
        ignore_index=True,
    )
    return candidates, official


def test_validation_selects_on_train_and_measures_frozen_variant_only() -> None:
    candidates, official = _monthly_inputs()

    selected = select_train_variant(
        candidates,
        official,
        signal="DivSeason",
        train_end="2010-12-31",
    )
    certificate = validate_frozen_variant(
        selected,
        candidates,
        official,
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        formula_sha256="f" * 64,
        source_manifest_sha256="s" * 64,
        gate=ForwardProxyGate(),
    )

    assert selected.variant_id == "faithful"
    assert certificate.variant_id == "faithful"
    assert certificate.validation_used_for_selection is False
    assert certificate.locked_opened is False
    assert certificate.passed is True


def test_post_2020_mutation_cannot_change_selection_or_validation() -> None:
    candidates, official = _monthly_inputs()
    selected = select_train_variant(
        candidates,
        official,
        signal="DivSeason",
        train_end="2010-12-31",
    )
    baseline = validate_frozen_variant(
        selected,
        candidates,
        official,
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        formula_sha256="f" * 64,
        source_manifest_sha256="s" * 64,
        gate=ForwardProxyGate(),
    )
    future_months = pd.date_range("2021-01-01", "2025-12-01", freq="MS")
    mutated_candidates = pd.concat(
        [
            candidates,
            pd.DataFrame(
                {
                    "signal": "DivSeason",
                    "variant_id": "faithful",
                    "month": future_months,
                    "proxy_return": 999.0,
                }
            ),
        ],
        ignore_index=True,
    )
    mutated_official = pd.concat(
        [
            official,
            pd.DataFrame(
                {
                    "signal": "DivSeason",
                    "month": future_months,
                    "official_return": -999.0,
                }
            ),
        ],
        ignore_index=True,
    )

    selected_after = select_train_variant(
        mutated_candidates,
        mutated_official,
        signal="DivSeason",
        train_end="2010-12-31",
    )
    after = validate_frozen_variant(
        selected_after,
        mutated_candidates,
        mutated_official,
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        formula_sha256="f" * 64,
        source_manifest_sha256="s" * 64,
        gate=ForwardProxyGate(),
    )

    assert selected_after == selected
    assert after == baseline


def test_failed_certificate_contributes_zero_score_weight() -> None:
    candidates, official = _monthly_inputs()
    selected = select_train_variant(
        candidates,
        official,
        signal="DivSeason",
        train_end="2010-12-31",
    )
    certificate = validate_frozen_variant(
        selected,
        candidates,
        official,
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        formula_sha256="f" * 64,
        source_manifest_sha256="s" * 64,
        gate=ForwardProxyGate(minimum_pearson=1.01),
    )
    current = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "signal": ["DivSeason"],
            "variant_id": ["faithful"],
            "formula_sha256": ["f" * 64],
            "source_manifest_sha256": ["s" * 64],
            "value": [1.0],
            "current_usable": [True],
            "base_score_weight": [0.8],
        }
    )

    result = apply_certificates(current, [certificate])

    assert result["current_usable"].eq(False).all()
    assert result["effective_score_weight"].eq(0.0).all()
    assert result["certificate_status"].eq("failed_validation_gate").all()


def test_certificate_hash_changes_when_formula_or_source_changes() -> None:
    candidates, official = _monthly_inputs()
    selected = select_train_variant(
        candidates,
        official,
        signal="DivSeason",
        train_end="2010-12-31",
    )
    certificate = validate_frozen_variant(
        selected,
        candidates,
        official,
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        formula_sha256="f" * 64,
        source_manifest_sha256="s" * 64,
        gate=ForwardProxyGate(),
    )

    assert certificate_sha256(certificate) != certificate_sha256(
        replace(certificate, formula_sha256="a" * 64)
    )
    assert certificate_sha256(certificate) != certificate_sha256(
        replace(certificate, source_manifest_sha256="b" * 64)
    )
