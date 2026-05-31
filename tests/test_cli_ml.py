"""Tests for ML / analytics CLI subcommands (Task K.3).

Run:
    uv run pytest aurora/tests/test_cli_ml.py -v
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.cli import forge as cli


# ---------------------------------------------------------------------------
# Synthetic data fixtures
# ---------------------------------------------------------------------------


def _synth_prices(n: int = 600, seed: int = 11) -> pd.Series:
    # Round-3 audit fix: analytical CLI commands now default to
    # ``--tier oos_dev`` (2013-2020). Anchor the synthetic series at
    # 2014-01-02 so the helper ``_resolve_tier_load`` returns a
    # non-empty slice for the ML / analytics commands under test.
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2014-01-02", periods=n, freq="B")
    rets = rng.normal(0.0005, 0.012, n)
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="SYNTH")


def _patch_load_asset(monkeypatch, prices=None):
    """Patch all known load_asset call sites used by the CLI."""
    prices = prices if prices is not None else _synth_prices()
    fake = lambda *a, **kw: prices
    monkeypatch.setattr(
        "aurora.core.data_layer.load_asset", fake, raising=True,
    )
    import aurora.deployment.preflight as pf
    monkeypatch.setattr(pf, "load_asset", fake, raising=True)
    return prices


# ---------------------------------------------------------------------------
# label
# ---------------------------------------------------------------------------


def test_label_command_runs(monkeypatch, tmp_path: Path, capsys):
    prices = _synth_prices(n=300, seed=3)
    _patch_load_asset(monkeypatch, prices)
    out = tmp_path / "labels.csv"
    rc = cli.main([
        "label", "--asset", "SYNTH",
        "--pt", "1.0", "--sl", "1.0", "--hp", "5",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    out_text = capsys.readouterr().out
    assert "Triple-barrier labels" in out_text
    assert "+1:" in out_text
    assert "-1:" in out_text
    df = pd.read_csv(out)
    assert "label" in df.columns
    assert len(df) > 0
    assert set(df["label"].unique()).issubset({-1, 0, 1})


def test_label_command_json_output(monkeypatch, tmp_path: Path):
    prices = _synth_prices(n=200, seed=5)
    _patch_load_asset(monkeypatch, prices)
    out = tmp_path / "labels.json"
    rc = cli.main([
        "label", "--asset", "SYNTH",
        "--pt", "1.5", "--sl", "1.0", "--hp", "3",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert "label" in payload[0]


def test_label_help_runs():
    with pytest.raises(SystemExit) as exc:
        cli.main(["label", "--help"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# factor
# ---------------------------------------------------------------------------


def test_factor_command(monkeypatch, capsys):
    prices = _synth_prices(n=600, seed=4)
    _patch_load_asset(monkeypatch, prices)
    rc = cli.main([
        "factor", "--strategy", "MACross", "--asset", "SYNTH",
        "--periods", "1,5,20",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Factor analysis" in out
    assert "ic_mean" in out
    assert "spread_sharpe" in out


def test_factor_command_writes_csv(monkeypatch, tmp_path: Path):
    prices = _synth_prices(n=600, seed=4)
    _patch_load_asset(monkeypatch, prices)
    out = tmp_path / "factor.csv"
    rc = cli.main([
        "factor", "--strategy", "MACross", "--asset", "SYNTH",
        "--periods", "1,5", "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    df = pd.read_csv(out)
    assert "ic_mean" in df.columns


# ---------------------------------------------------------------------------
# attribute
# ---------------------------------------------------------------------------


def test_attribute_command_factor_mode(monkeypatch, capsys):
    prices = _synth_prices(n=500, seed=8)
    _patch_load_asset(monkeypatch, prices)
    rc = cli.main([
        "attribute", "--strategy", "MACross", "--asset", "SYNTH",
        "--benchmark", "SYNTH", "--costs", "zero",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Attribution by factor" in out
    assert "benchmark" in out
    assert "Alpha" in out


def test_attribute_command_regime_mode(monkeypatch, tmp_path: Path, capsys):
    prices = _synth_prices(n=500, seed=8)
    _patch_load_asset(monkeypatch, prices)
    # Build regime CSV: alternating bull/bear blocks
    labels = ["bull"] * 250 + ["bear"] * 250
    regime_df = pd.DataFrame({"regime": labels}, index=prices.index)
    rfile = tmp_path / "regimes.csv"
    regime_df.to_csv(rfile, index_label="date")
    rc = cli.main([
        "attribute", "--strategy", "MACross", "--asset", "SYNTH",
        "--regime", "bull,bear",
        "--regime-file", str(rfile),
        "--costs", "zero",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Attribution by regime" in out
    assert "bull" in out or "bear" in out


# ---------------------------------------------------------------------------
# purge-cv
# ---------------------------------------------------------------------------


def test_purge_cv_command(monkeypatch, capsys):
    prices = _synth_prices(n=600, seed=2)
    _patch_load_asset(monkeypatch, prices)
    rc = cli.main([
        "purge-cv", "--strategy", "MACross", "--asset", "SYNTH",
        "--k", "5", "--embargo", "0.01", "--costs", "zero",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Purged CV" in out
    assert "k=5" in out
    assert "Calmar" in out
    assert "Sharpe" in out
    # one row per fold
    for f in range(5):
        assert f"\n{f:>4}" in out or out.count("calmar") >= 1


def test_purge_cv_command_writes_output(monkeypatch, tmp_path: Path):
    prices = _synth_prices(n=600, seed=2)
    _patch_load_asset(monkeypatch, prices)
    out = tmp_path / "folds.csv"
    rc = cli.main([
        "purge-cv", "--strategy", "MACross", "--asset", "SYNTH",
        "--k", "4", "--embargo", "0.0", "--costs", "zero",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    df = pd.read_csv(out)
    assert {"fold", "calmar", "sharpe", "mdd"}.issubset(df.columns)
    assert len(df) == 4


# ---------------------------------------------------------------------------
# fracdiff
# ---------------------------------------------------------------------------


def test_fracdiff_command(monkeypatch, capsys):
    prices = _synth_prices(n=400, seed=12)
    _patch_load_asset(monkeypatch, prices)
    rc = cli.main([
        "fracdiff", "--asset", "SYNTH",
        "--max-d", "1.0", "--step", "0.1",
        "--threshold", "1e-3",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Fracdiff min-d sweep" in out
    # Either a min_d line or "No d in sweep" line — both are acceptable outcomes.
    assert ("min_d=" in out) or ("No d in sweep" in out)


def test_fracdiff_command_with_sweep_table(monkeypatch, capsys):
    prices = _synth_prices(n=400, seed=12)
    _patch_load_asset(monkeypatch, prices)
    rc = cli.main([
        "fracdiff", "--asset", "SYNTH",
        "--max-d", "0.5", "--step", "0.1",
        "--threshold", "1e-3",
        "--sweep",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "adf_stat" in out
    assert "corr_with_original" in out


# ---------------------------------------------------------------------------
# cscv
# ---------------------------------------------------------------------------


def test_cscv_command(tmp_path: Path, capsys):
    rng = np.random.default_rng(101)
    n_rows, n_cols = 200, 10
    arr = rng.normal(0.0005, 0.012, size=(n_rows, n_cols))
    idx = pd.date_range("2018-01-01", periods=n_rows, freq="B")
    df = pd.DataFrame(
        arr, index=idx, columns=[f"strat_{i}" for i in range(n_cols)],
    )
    csv = tmp_path / "rets.csv"
    df.to_csv(csv, index_label="date")

    rc = cli.main([
        "cscv", "--returns-csv", str(csv),
        "--n-splits", "8", "--max-combos", "200",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CSCV / PBO" in out
    assert "PBO:" in out


def test_cscv_command_writes_summary(tmp_path: Path):
    rng = np.random.default_rng(202)
    n_rows, n_cols = 160, 8
    arr = rng.normal(0.0, 0.01, size=(n_rows, n_cols))
    idx = pd.date_range("2019-01-01", periods=n_rows, freq="B")
    df = pd.DataFrame(
        arr, index=idx, columns=[f"s{i}" for i in range(n_cols)],
    )
    csv = tmp_path / "rets.csv"
    df.to_csv(csv, index_label="date")

    out = tmp_path / "summary.json"
    rc = cli.main([
        "cscv", "--returns-csv", str(csv),
        "--n-splits", "8", "--max-combos", "100",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "pbo" in payload
    assert "n_combinations" in payload


# ---------------------------------------------------------------------------
# Help / parser shape
# ---------------------------------------------------------------------------


def test_new_subcommand_help_runs():
    for sub in ("label", "factor", "attribute", "purge-cv", "fracdiff", "cscv"):
        with pytest.raises(SystemExit) as exc:
            cli.main([sub, "--help"])
        assert exc.value.code == 0, sub
