from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import crypto_trend as ct


def _prices(end: str = "2023-12-31", seed: int = 2) -> pd.DataFrame:
    idx = pd.date_range("2015-01-01", end, freq="D")
    rng = np.random.default_rng(seed)
    data = {a: 100 * np.cumprod(1 + rng.normal(0.001, 0.04, len(idx))) for a in ct.ALTS}
    prices = pd.DataFrame(data, index=idx)
    prices["CASH"] = 100 * (1 + 0.02 / 365) ** np.arange(len(idx))
    return prices


def test_rebalance_dates_pick_the_weekday() -> None:
    idx = pd.date_range("2024-01-01", periods=14, freq="D")
    assert all(d.weekday() == 6 for d in ct.rebalance_dates(idx))
    assert len(ct.rebalance_dates(idx, None)) == 14


def test_ma_ensemble_is_the_fraction_of_votes() -> None:
    idx = pd.date_range("2020-01-01", periods=150, freq="D")
    close = pd.DataFrame({"BTC": np.linspace(100, 200, 150)}, index=idx)
    sig = ct.ma_ensemble(close, pd.Series(1.0, index=idx))
    assert sig["BTC"].iloc[-1] == 1.0
    assert sig["BTC"].iloc[30] == pytest.approx(1 / 3)  # only SMA20 defined yet


def test_donchian_enters_on_high_and_exits_on_low() -> None:
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    path = np.r_[np.linspace(100, 120, 30), np.linspace(120, 90, 30)]
    sig = ct.donchian_20_10(pd.DataFrame({"BTC": path}, index=idx), pd.Series(1.0, index=idx))
    assert sig["BTC"].iloc[25] == 1.0
    assert sig["BTC"].iloc[-1] == 0.0


def test_weights_respect_vol_sizing_and_no_leverage() -> None:
    prices = _prices()
    w = ct.target_weights(prices, ct.ma_ensemble, ct.CORE)
    risky = w[ct.CORE]
    assert (risky.sum(axis=1) <= 1.0 + 1e-12).all()
    assert (risky <= 0.5 + 1e-12).all().all()  # min(1, vol ratio) / N with N = 2
    assert (w["CASH"] >= -1e-12).all()


def test_tsmom_compares_with_cash() -> None:
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    flat = pd.DataFrame({"BTC": np.full(60, 100.0)}, index=idx)
    cash = pd.Series(np.linspace(100, 101, 60), index=idx)
    assert ct.tsmom_28(flat, cash)["BTC"].iloc[-1] == 0.0


def test_run_study_rejects_locked_data() -> None:
    with pytest.raises(ValueError, match="locked"):
        ct.run_study(_prices(end="2024-01-02"))


def test_run_study_reports_every_candidate_with_criteria() -> None:
    out = ct.run_study(_prices())
    res = out["results"]
    assert set(res) == {ct.BENCHMARK, *ct.CANDIDATES}
    for name in ct.CANDIDATES:
        assert res[name]["validation"]["start"] >= "2022-01-01"
        assert res[name]["validation"]["end"] <= "2023-12-31"
        assert len(res[name]["checks"]) == 3
        assert set(res[name]["robustness"]) == {"weekday_2", "weekday_4", "daily", "cost_15bps", "cost_60bps"}


def _script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_crypto_trend.py"
    spec = importlib.util.spec_from_file_location("run_crypto_trend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cash_accrues_only_on_business_days() -> None:
    script = _script()
    calendar = pd.date_range("2023-12-22", "2023-12-27", freq="D")  # Christmas Monday 25th
    index = pd.Series(np.cumprod(np.full(len(calendar), 1.0001)), index=calendar)
    cash = script.business_day_cash(index, calendar).pct_change().fillna(0.0)
    assert cash.loc["2023-12-23"] == 0.0  # Saturday
    assert cash.loc["2023-12-25"] == 0.0  # federal holiday
    assert cash.loc["2023-12-26"] > 0.0


def test_sealed_drops_locked_observations_before_cleanup() -> None:
    script = _script()
    s = pd.Series(1.0, index=pd.date_range("2023-12-30", "2024-01-03", freq="D"))
    assert script._sealed(s).index.max() == pd.Timestamp("2023-12-31")
