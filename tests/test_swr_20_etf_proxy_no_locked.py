from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_swr_20_etf_proxy_2000_no_locked.py"
CONFIG_PATH = ROOT / "config" / "swr_20_etf_proxy_2000_no_locked_360jobs.yaml"


spec = importlib.util.spec_from_file_location("swr_no_locked", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
swr = importlib.util.module_from_spec(spec)
sys.modules["swr_no_locked"] = swr
spec.loader.exec_module(swr)


def test_campaign_shape_is_20_families_360_jobs() -> None:
    config = swr.load_config(CONFIG_PATH)

    swr.validate_campaign_shape(config)

    assert len(config["families"]) == 20
    assert config["github"]["shards_per_family"] == 18
    assert config["github"]["total_jobs"] == 360
    assert config["github"]["max_parallel"] == 360


def test_locked_dates_are_rejected() -> None:
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2019-12-31", "2020-01-31"])})

    with pytest.raises(ValueError, match="locked data opened"):
        swr.validate_no_locked_dates(frame, "timestamp", "2020-01-01")


def test_concrete_stock_is_rejected() -> None:
    config = swr.load_config(CONFIG_PATH)
    bad = copy.deepcopy(config)
    bad["sleeves"]["us_equity"]["tradable_etf"] = "AAPL"

    with pytest.raises(ValueError, match="concrete stock"):
        swr.validate_universe(bad)


def test_crypto_is_rejected() -> None:
    config = swr.load_config(CONFIG_PATH)
    bad = copy.deepcopy(config)
    bad["sleeves"]["cash"]["proxy_symbol"] = "BTCUSDT"

    with pytest.raises(ValueError, match="crypto"):
        swr.validate_universe(bad)


def test_shard_smoke_writes_outputs_without_locked(tmp_path: Path) -> None:
    config = swr.load_config(CONFIG_PATH)
    local = swr.with_smoke_runtime_limits(config)
    local["github"]["configs_per_shard"] = 1
    returns, proxy_map, data_audit = swr.build_synthetic_proxy_returns(local)

    swr.run_shard(tmp_path, local, returns, proxy_map, data_audit, family_id=0, shard_id=0)

    shard = tmp_path / "shards" / "family_00_shard_00"
    assert (shard / "all_candidates_metrics.parquet").exists()
    assert (shard / "pruned_by_job.csv").exists()
    locked = pd.read_csv(shard / "locked_access_audit.csv")
    assert int(locked.loc[0, "locked_rows_accessed"]) == 0
    assert bool(locked.loc[0, "locked_opened"]) is False
