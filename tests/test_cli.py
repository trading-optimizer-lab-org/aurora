"""Tests for quantforge.cli.forge.

Use the in-process build_parser/main entrypoints rather than spawning subprocesses
where possible: faster, no environment churn, and synthetic data injection works
via monkeypatch on quantforge.core.data_layer.load_asset.
"""
from __future__ import annotations
import io
import os
import sys
import json
import contextlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantforge.cli import forge as cli


# ---------------------------------------------------------------------------
# Synthetic price helper used by data-driven CLI tests
# ---------------------------------------------------------------------------


def _synth_prices(n: int = 600, seed: int = 11) -> pd.Series:
    # Round-3 audit fix: the analytical CLI commands now default to
    # ``--tier oos_dev`` (2013-2020). Anchoring the synthetic series at
    # 2014-01-02 keeps every window fully inside OOS_DEV so the helper
    # ``_resolve_tier_load`` returns a non-empty slice.
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2014-01-02", periods=n, freq="B")
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="SYNTH")


def _patch_load_asset(monkeypatch, prices=None):
    """Patch all known load_asset call sites used by the CLI."""
    prices = prices if prices is not None else _synth_prices()
    fake = lambda *a, **kw: prices
    # forge module imports load_asset lazily inside command bodies, so patch the
    # original locations.
    monkeypatch.setattr(
        "quantforge.core.data_layer.load_asset", fake, raising=True,
    )
    # The preflight module captured load_asset at import time (from-import).
    import quantforge.deployment.preflight as pf
    monkeypatch.setattr(pf, "load_asset", fake, raising=True)
    return prices


# ---------------------------------------------------------------------------
# --help / parser shape
# ---------------------------------------------------------------------------


def test_help_runs():
    """forge --help should exit 0."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_subcommand_help_runs():
    for sub in ("run", "validate", "search", "list-strategies",
                "tearsheet", "bench", "preflight"):
        with pytest.raises(SystemExit) as exc:
            cli.main([sub, "--help"])
        assert exc.value.code == 0, sub


def test_config_subcommand_help():
    for sub in ("show", "init"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["config", sub, "--help"])
        assert exc.value.code == 0, sub


def test_no_command_errors():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    # argparse exits 2 for missing required subcommand
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# list-strategies
# ---------------------------------------------------------------------------


def test_list_strategies(capsys):
    rc = cli.main(["list-strategies"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MACross" in out
    assert "RSIMeanRev" in out
    assert "Total:" in out
    # at least the names from library.__all__ should be listed
    from quantforge.strategies import library as lib_mod
    for n in lib_mod.__all__:
        assert n in out


# ---------------------------------------------------------------------------
# config show / init
# ---------------------------------------------------------------------------


def test_config_show_defaults(capsys):
    rc = cli.main(["config", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "data:" in out or "data" in out
    assert "ibkr" in out  # default cost profile


def test_config_show_json(capsys):
    rc = cli.main(["config", "show", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["seed"] == 42
    assert payload["costs"]["profile"] == "ibkr"


def test_config_init_creates_file(tmp_path: Path, capsys):
    out = tmp_path / "myconfig.yaml"
    rc = cli.main(["config", "init", "--output", str(out)])
    assert rc == 0
    assert out.exists()
    # Round-trip load to verify validity
    from quantforge.core.config import load_config
    cfg = load_config(out)
    assert cfg.seed == 42
    msg = capsys.readouterr().out
    assert "Default config written" in msg


def test_config_init_refuses_overwrite(tmp_path: Path, capsys):
    out = tmp_path / "exists.yaml"
    out.write_text("seed: 99\n", encoding="utf-8")
    rc = cli.main(["config", "init", "--output", str(out)])
    assert rc == 1
    assert "Refusing to overwrite" in capsys.readouterr().out
    # original content unchanged
    assert "seed: 99" in out.read_text(encoding="utf-8")


def test_config_init_force_overwrites(tmp_path: Path):
    out = tmp_path / "exists.yaml"
    out.write_text("seed: 99\n", encoding="utf-8")
    rc = cli.main(["config", "init", "--output", str(out), "--force"])
    assert rc == 0
    from quantforge.core.config import load_config
    cfg = load_config(out)
    assert cfg.seed == 42  # default re-written


def test_config_show_with_path(tmp_path: Path, capsys):
    """Top-level --config <path> should load that config."""
    p = tmp_path / "mine.yaml"
    p.write_text("seed: 7\nlog_level: DEBUG\n", encoding="utf-8")
    rc = cli.main(["--config", str(p), "config", "show", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["seed"] == 7
    assert payload["log_level"] == "DEBUG"


def test_config_load_missing_file_exits():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", "no_such_file.yaml", "list-strategies"])
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Invalid strategy returns error
# ---------------------------------------------------------------------------


def test_invalid_strategy_returns_error_code(capsys, monkeypatch):
    _patch_load_asset(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--strategy", "DoesNotExist", "--asset", "FAKE"])
    # _resolve_strategy raises SystemExit with a string message: code != 0
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# run command (basic, with synthetic data)
# ---------------------------------------------------------------------------


def test_run_command_basic(monkeypatch, capsys):
    _patch_load_asset(monkeypatch)
    rc = cli.main([
        "run", "--strategy", "MACross", "--asset", "FAKE",
        "--costs", "zero", "--seed", "42",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Strategy: MACross on FAKE" in out
    assert "Calmar:" in out
    assert "Sharpe:" in out


# ---------------------------------------------------------------------------
# tearsheet command
# ---------------------------------------------------------------------------


def test_tearsheet_writes_file(monkeypatch, tmp_path, capsys):
    _patch_load_asset(monkeypatch, _synth_prices(n=400))
    out = tmp_path / "ts.html"
    rc = cli.main([
        "tearsheet", "--strategy", "MACross", "--asset", "FAKE",
        "--output", str(out), "--costs", "zero",
    ])
    assert rc == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<html" in content.lower()
    assert "MACross" in content
    msg = capsys.readouterr().out
    assert "Tearsheet written" in msg


# ---------------------------------------------------------------------------
# bench command
# ---------------------------------------------------------------------------


def test_bench_runs(capsys):
    rc = cli.main([
        "bench", "--strategy", "MACross", "--n", "300", "--repeats", "1",
        "--costs", "zero",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Sequential" in out
    # JIT line is printed even on numpy fallback or unavailable engine
    assert ("JIT" in out) or ("JIT engine unavailable" in out)


# ---------------------------------------------------------------------------
# preflight command
# ---------------------------------------------------------------------------


def test_preflight_runs(monkeypatch, tmp_path, capsys):
    """Marker is missing -> overall fail expected, but the command must complete
    and print a PREFLIGHT REPORT."""
    _patch_load_asset(monkeypatch, _synth_prices(n=400))
    rc = cli.main([
        "preflight", "--strategy", "MACross", "--symbol", "FAKE",
        "--min-bars", "100", "--project-dir", str(tmp_path),
        "--min-disk-mb", "1",
    ])
    # marker absent -> exit 1
    assert rc == 1
    out = capsys.readouterr().out
    assert "PREFLIGHT REPORT" in out
    assert "OVERALL:" in out


def test_preflight_pass_with_marker(monkeypatch, tmp_path, capsys):
    """Write a valid marker so all gates pass."""
    prices = _synth_prices(n=400)
    _patch_load_asset(monkeypatch, prices)
    from quantforge.deployment.preflight import write_validation_marker
    write_validation_marker(
        "MACross", {"is": {"calmar": 1.1}}, project_dir=str(tmp_path),
    )
    rc = cli.main([
        "preflight", "--strategy", "MACross", "--symbol", "FAKE",
        "--min-bars", "100", "--project-dir", str(tmp_path),
        "--min-disk-mb", "1",
    ])
    out = capsys.readouterr().out
    assert "PREFLIGHT REPORT" in out
    # may pass or fail depending on environment (disk, net) but report rendered
    assert rc in (0, 1)
