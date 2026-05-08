"""Tests for quantforge.core.config: pydantic validation, YAML/TOML I/O, overrides."""
from __future__ import annotations
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantforge.core.config import (
    ForgeConfig,
    DataConfig,
    CostConfig,
    ValidationConfig,
    GAConfig,
    default_config,
    load_config,
    save_config,
    merge_overrides,
)


def test_default_config():
    cfg = default_config()
    assert isinstance(cfg, ForgeConfig)
    assert cfg.seed == 42
    assert cfg.log_level == "INFO"
    assert cfg.data.is_start == "1995-01-01"
    assert cfg.data.is_end == "2012-12-31"
    assert cfg.data.oos_start == "2013-01-01"
    assert cfg.data.oos_end == "2024-12-31"
    # cache_dir resolves via runtime_paths (honours $QF_CACHE_DIR /
    # $QF_DATA_DIR; falls back to platformdirs user-data dir). The legacy
    # in-repo `quantforge/data_cache_qf` default was retired so the
    # ghost directory it created stops shadowing the package.
    from quantforge.core.runtime_paths import cache_dir as _cache_dir
    assert cfg.data.cache_dir == str(_cache_dir())
    assert cfg.costs.profile == "ibkr"
    assert cfg.costs.commission_bps == 0.5
    assert cfg.costs.spread_bps == 1.0
    assert cfg.costs.slippage_bps == 2.0
    assert cfg.costs.borrow_rate_annual == 0.01
    assert cfg.validation.min_wf_pass == 3
    assert cfg.validation.spp_max_cv == 0.30
    assert cfg.validation.mc_min_pct == 0.20
    assert cfg.validation.mc_max_pct == 0.80
    assert cfg.validation.min_dsr == 0.95
    assert cfg.validation.mc_n_paths == 500
    assert cfg.validation.mc_block_size == 21
    assert cfg.ga.population == 200
    assert cfg.ga.generations == 50
    assert cfg.ga.crossover_prob == 0.7
    assert cfg.ga.mutation_prob == 0.2
    assert cfg.ga.seed == 42


def test_load_yaml(tmp_path: Path):
    yaml_content = """
data:
  is_start: "2000-01-01"
  is_end: "2010-12-31"
  oos_start: "2011-01-01"
  oos_end: "2020-12-31"
  cache_dir: "custom_cache"

costs:
  profile: conservative
  commission_bps: 2.0
  spread_bps: 5.0
  slippage_bps: 10.0
  borrow_rate_annual: 0.03

validation:
  min_wf_pass: 5
  spp_max_cv: 0.25
  mc_min_pct: 0.15
  mc_max_pct: 0.85
  min_dsr: 0.99

ga:
  population: 300
  generations: 100
  seed: 7

seed: 7
log_level: DEBUG
"""
    p = tmp_path / "test.yaml"
    p.write_text(yaml_content, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.seed == 7
    assert cfg.log_level == "DEBUG"
    assert cfg.data.is_start == "2000-01-01"
    assert cfg.data.cache_dir == "custom_cache"
    assert cfg.costs.profile == "conservative"
    assert cfg.costs.commission_bps == 2.0
    assert cfg.validation.min_wf_pass == 5
    assert cfg.validation.min_dsr == 0.99
    assert cfg.ga.population == 300
    assert cfg.ga.generations == 100
    assert cfg.ga.seed == 7


def test_load_toml(tmp_path: Path):
    toml_content = """
seed = 13
log_level = "WARNING"

[data]
is_start = "2001-01-01"
is_end = "2011-12-31"
oos_start = "2012-01-01"
oos_end = "2022-12-31"
cache_dir = "toml_cache"

[costs]
profile = "zero"
commission_bps = 0.0
spread_bps = 0.0
slippage_bps = 0.0
borrow_rate_annual = 0.0

[validation]
min_wf_pass = 4
spp_max_cv = 0.35
mc_min_pct = 0.10
mc_max_pct = 0.90
min_dsr = 0.90
mc_n_paths = 1000
mc_block_size = 30

[ga]
population = 150
generations = 25
crossover_prob = 0.6
mutation_prob = 0.3
seed = 13
"""
    p = tmp_path / "test.toml"
    p.write_text(toml_content, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.seed == 13
    assert cfg.log_level == "WARNING"
    assert cfg.data.is_start == "2001-01-01"
    assert cfg.data.cache_dir == "toml_cache"
    assert cfg.costs.profile == "zero"
    assert cfg.costs.commission_bps == 0.0
    assert cfg.validation.min_wf_pass == 4
    assert cfg.validation.mc_n_paths == 1000
    assert cfg.ga.population == 150
    assert cfg.ga.crossover_prob == 0.6


def test_merge_overrides():
    cfg = default_config()
    merged = merge_overrides(cfg, {"seed": 999, "ga": {"population": 50}})
    # Original untouched
    assert cfg.seed == 42
    assert cfg.ga.population == 200
    # Merged has overrides applied
    assert merged.seed == 999
    assert merged.ga.population == 50
    # Untouched fields preserved
    assert merged.ga.generations == 50
    assert merged.log_level == "INFO"
    assert merged.costs.profile == "ibkr"


def test_merge_overrides_empty():
    cfg = default_config()
    merged = merge_overrides(cfg, {})
    assert merged.model_dump() == cfg.model_dump()


def test_validation_bad_value():
    # population must be int; non-numeric string should fail
    with pytest.raises(ValidationError):
        ForgeConfig.model_validate({"ga": {"population": "not_an_int"}})

    with pytest.raises(ValidationError):
        ForgeConfig.model_validate({"validation": {"mc_n_paths": "abc"}})

    with pytest.raises(ValidationError):
        ForgeConfig.model_validate({"seed": "definitely_not_an_int"})


def test_save_load_roundtrip_yaml(tmp_path: Path):
    cfg = default_config()
    cfg = merge_overrides(cfg, {
        "seed": 7,
        "log_level": "DEBUG",
        "data": {"cache_dir": "roundtrip_yaml"},
        "costs": {"profile": "conservative", "commission_bps": 3.5},
        "ga": {"population": 77},
    })
    p = tmp_path / "roundtrip.yaml"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.model_dump() == cfg.model_dump()


def test_save_load_roundtrip_toml(tmp_path: Path):
    pytest.importorskip("tomli_w")
    cfg = default_config()
    cfg = merge_overrides(cfg, {
        "seed": 11,
        "log_level": "ERROR",
        "validation": {"min_wf_pass": 7, "mc_n_paths": 333},
        "ga": {"population": 88, "generations": 12},
    })
    p = tmp_path / "roundtrip.toml"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.model_dump() == cfg.model_dump()


def test_unsupported_extension(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported config extension"):
        load_config(p)


def test_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_example_yaml_loads():
    """The shipped example file at quantforge/docs/config.example.yaml must parse."""
    here = Path(__file__).resolve().parent
    example = here.parent / "docs" / "config.example.yaml"
    assert example.exists(), f"Expected example config at {example}"
    cfg = load_config(example)
    # Sanity: example matches the documented defaults
    assert cfg.seed == 42
    assert cfg.costs.profile == "ibkr"
    assert cfg.ga.population == 200
