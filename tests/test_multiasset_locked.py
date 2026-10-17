from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import multiasset_locked as locked

ASSETS = ["SPY", "TLT", "IEF", "GLD", "DBC", "EFA", "EEM", "AGG", "LQD", "SHY"]


def _prices(end: str) -> pd.DataFrame:
    idx = pd.bdate_range("2015-01-01", end)
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0003, 0.008, size=(len(idx), len(ASSETS)))
    prices = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=ASSETS)
    prices["CASH"] = 100 * (1 + 0.02 / 252) ** np.arange(len(idx))
    return prices


def test_requires_locked_data() -> None:
    with pytest.raises(ValueError, match="no locked-period data"):
        locked.evaluate_locked(_prices("2020-12-31"), today=pd.Timestamp("2021-01-05"))


def test_reports_only_the_locked_period_with_preregistered_checks() -> None:
    out = locked.evaluate_locked(_prices("2023-06-30"), today=pd.Timestamp("2023-07-03"))
    cand = out[locked.CANDIDATE]
    assert cand["start"] >= "2021-01-01"
    assert set(cand["annual_returns"]) == {"2021", "2022", "2023"}
    assert list(out["checks"]) == list(locked.CRITERIA)
    assert out["passed"] == all(out["checks"].values())


def test_script_refuses_without_the_exact_authorization(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_multiasset_locked_once.py"
    spec = importlib.util.spec_from_file_location("run_multiasset_locked_once", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", ["x", "--authorization", "nope"])
    with pytest.raises(SystemExit, match="authorization"):
        module.main()


def test_refuses_stale_data() -> None:
    with pytest.raises(ValueError, match="days before the run"):
        locked.evaluate_locked(_prices("2023-06-30"), today=pd.Timestamp("2023-08-15"))


def test_drops_the_unfinished_month() -> None:
    out = locked.evaluate_locked(_prices("2023-06-14"), today=pd.Timestamp("2023-06-15"))
    assert out["evaluated_through"] == "2023-05-31"
    assert out[locked.CANDIDATE]["end"] == "2023-05-31"


def test_drawdown_counts_a_first_day_loss() -> None:
    r = pd.Series([-0.10, 0.05], index=pd.bdate_range("2021-01-04", periods=2))
    assert locked._drawdown_from_start(r) == pytest.approx(-0.10)
