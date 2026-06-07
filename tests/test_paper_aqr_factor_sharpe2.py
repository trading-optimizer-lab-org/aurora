from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_paper_aqr_factor_sharpe2.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_paper_aqr_factor_sharpe2", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_volatility_managed_uses_one_day_lag() -> None:
    module = load_module()
    idx = pd.date_range("2000-01-01", periods=8, freq="D")
    base = pd.Series([0.01, -0.01, 0.02, -0.02, 0.03, -0.03, 0.04, -0.04], index=idx)

    _scaled, scale = module.volatility_managed(base, lookback=3, max_scale=5.0, target=0.01)
    unshifted = (0.01 / base.rolling(3, min_periods=3).std(ddof=0).replace(0.0, pd.NA)).clip(0.0, 5.0)

    assert float(scale.iloc[0]) == 1.0
    assert scale.iloc[5] == unshifted.iloc[4]


def test_candidate_manifest_is_paper_sourced() -> None:
    module = load_module()
    candidates = module.build_candidates(["bab_Global", "qmj_Global", "hml_devil_Global"])

    assert candidates
    assert any("Betting Against Beta" in candidate.source_papers for candidate in candidates)
    assert all(candidate.strategy_type in {"paper_factor_benchmark_proxy", "multi_paper_proxy"} for candidate in candidates)


def test_evaluate_candidate_keeps_locked_and_validation_flags_false() -> None:
    module = load_module()
    idx = pd.date_range("1995-01-02", "2020-12-31", freq="B")
    returns = pd.Series(0.001, index=idx, name="strategy_return")
    weights = pd.DataFrame({"bab_Global": 1.0}, index=idx)
    candidate = module.Candidate(
        candidate_id="aqr_test",
        strategy_name="test",
        source_papers="Betting Against Beta",
        strategy_type="paper_factor_benchmark_proxy",
        rule="test",
        factor_columns=("bab_Global",),
        transform="raw_factor",
    )

    row = module.evaluate_candidate(candidate, returns, weights)

    assert row["locked_opened"] is False
    assert row["validation_used_for_selection"] is False
    assert row["paper_exact_replication_claimed"] is False
