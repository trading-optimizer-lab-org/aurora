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
        locked.evaluate_locked(_prices("2020-12-31"))


def test_reports_only_the_locked_period_with_preregistered_checks() -> None:
    out = locked.evaluate_locked(_prices("2023-06-30"))
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
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", ["x", "--authorization", "nope"])
    with pytest.raises(SystemExit, match="authorization"):
        module.main()
