"""YAML/TOML config system for QuantForge with pydantic v2 validation.

Loaded explicitly. No singletons. Pass ForgeConfig to functions.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    is_start: str = "1995-01-01"
    is_end: str = "2012-12-31"
    oos_start: str = "2013-01-01"
    oos_end: str = "2024-12-31"
    cache_dir: str = "quantforge/data_cache_qf"


class CostConfig(BaseModel):
    profile: str = "ibkr"  # zero | ibkr | conservative | custom
    commission_bps: float = 0.5
    spread_bps: float = 1.0
    slippage_bps: float = 2.0
    borrow_rate_annual: float = 0.01


class ValidationConfig(BaseModel):
    """Thresholds for the four anti-overfit validation gates.

    Field-by-field reference:

    min_wf_pass
        Minimum walk-forward windows where the strategy's Calmar exceeds
        buy-and-hold Calmar. Unit: count of WF windows (integer >= 0).
        Default 3 mirrors the gate in `validation/walk_forward.py`.
    spp_max_cv
        Maximum allowed coefficient of variation for SPP (System Parameter
        Permutation) Calmar in the +/-10% neighborhood. Unit: dimensionless
        ratio (stdev/mean). Default 0.30 = "30% CV ceiling".
    mc_min_pct
        Lower percentile bound (inclusive) of the Monte Carlo bootstrap
        distribution for the realized max-drawdown to fall within. Unit:
        cumulative probability in [0,1]. Default 0.20 = P20.
    mc_max_pct
        Upper percentile bound (inclusive) of the Monte Carlo bootstrap
        distribution for the realized max-drawdown. Unit: cumulative
        probability in [0,1]. Default 0.80 = P80.
    min_dsr
        Minimum Deflated Sharpe Ratio (Bailey & Lopez de Prado) post
        candidate selection. Unit: probability that the true Sharpe is
        positive after multiple-testing correction (in [0,1]). Default 0.95.
    mc_n_paths
        Number of bootstrap paths used when generating the Monte Carlo
        drawdown distribution. Unit: count of paths (integer > 0).
        Default 500. Higher = tighter CIs, longer runtime.
    mc_block_size
        Block length (in bars) for the stationary bootstrap that preserves
        autocorrelation structure during MC resampling. Unit: bars (typically
        trading days for daily data). Default 21 ~= one trading month.
    """

    min_wf_pass: int = 3
    spp_max_cv: float = 0.30
    mc_min_pct: float = 0.20
    mc_max_pct: float = 0.80
    min_dsr: float = 0.95
    mc_n_paths: int = 500
    mc_block_size: int = 21


class GAConfig(BaseModel):
    population: int = 200
    generations: int = 50
    crossover_prob: float = 0.7
    mutation_prob: float = 0.2
    seed: int = 42


class ForgeConfig(BaseModel):
    """Top-level config combining all sub-configs."""
    data: DataConfig = Field(default_factory=DataConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    ga: GAConfig = Field(default_factory=GAConfig)
    seed: int = 42
    log_level: str = "INFO"


def default_config() -> ForgeConfig:
    """Return ForgeConfig with all defaults."""
    return ForgeConfig()


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be mapping, got {type(data).__name__}")
    return data


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: str | Path) -> ForgeConfig:
    """Load YAML or TOML based on file extension."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        raw = _load_yaml(p)
    elif suffix == ".toml":
        raw = _load_toml(p)
    else:
        raise ValueError(f"Unsupported config extension: {suffix}. Use .yaml/.yml/.toml")
    return ForgeConfig.model_validate(raw)


def _save_yaml(data: dict[str, Any], path: Path) -> None:
    import yaml
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


def _save_toml(data: dict[str, Any], path: Path) -> None:
    try:
        import tomli_w
    except ImportError as e:
        raise RuntimeError(
            "Saving TOML requires 'tomli-w'. Install with: pip install tomli-w"
        ) from e
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def save_config(config: ForgeConfig, path: str | Path) -> None:
    """Save to YAML or TOML based on file extension."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        _save_yaml(data, p)
    elif suffix == ".toml":
        _save_toml(data, p)
    else:
        raise ValueError(f"Unsupported config extension: {suffix}. Use .yaml/.yml/.toml")


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def merge_overrides(config: ForgeConfig, overrides: dict) -> ForgeConfig:
    """Deep-merge override dict (e.g. from CLI args) onto config.

    Returns a new ForgeConfig. Original is not mutated.
    """
    base = config.model_dump()
    merged = _deep_merge(base, overrides or {})
    return ForgeConfig.model_validate(merged)
