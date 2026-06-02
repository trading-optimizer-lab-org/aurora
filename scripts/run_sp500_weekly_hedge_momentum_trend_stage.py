from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_search_module():
    module_path = ROOT / "research" / "sp500_weekly_hedge_search.py"
    spec = importlib.util.spec_from_file_location("sp500_weekly_hedge_search_runtime", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load SP500 hedge search module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


_SEARCH = _load_search_module()
SP500WeeklyHedgeConfig = _SEARCH.SP500WeeklyHedgeConfig
load_dataset = _SEARCH.load_dataset
run_stage = _SEARCH.run_stage


def _load_search_quality_module():
    module_path = ROOT / "research" / "search_quality.py"
    spec = importlib.util.spec_from_file_location("search_quality_runtime", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load search-quality module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


_SEARCH_QUALITY = _load_search_quality_module()
SearchQualityConfig = _SEARCH_QUALITY.SearchQualityConfig
SearchQualityState = _SEARCH_QUALITY.SearchQualityState
early_prune_reason = _SEARCH_QUALITY.early_prune_reason
filter_features_by_history = _SEARCH_QUALITY.filter_features_by_history
robust_train_score = _SEARCH_QUALITY.robust_train_score
simple_soft_robustness = _SEARCH_QUALITY.simple_soft_robustness

ALLOWED_SUFFIXES = (
    "__ret_1w",
    "__ret_4w",
    "__ret_13w",
    "__ret_26w",
    "__vol_4w",
    "__vol_13w",
    "__ma_gap_10w",
    "__ma_gap_30w",
    "__drawdown_26w",
    "__corr_spy_13w",
    "__beta_spy_13w",
)
FORBIDDEN_FEATURE_TOKENS = (
    "btc",
    "eth",
    "crypto",
    "binance",
    "usdt",
    "cftc",
    "sec",
    "bls",
    "calendar",
    "politic",
    "election",
)
CRYPTO_TOKENS = ("btc", "eth", "crypto", "binance", "usdt")
QUALITY_FAMILIES = (
    "spy_momentum",
    "spy_trend_drawdown",
    "trend_volatility",
    "relative_etf",
    "vix_trend",
    "mixed",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one SPY-only momentum/trend weekly hedge DEHB stage.")
    parser.add_argument("--wave", type=int, default=0)
    parser.add_argument("--total-waves", type=int, default=1)
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--total-stages", type=int, default=500)
    parser.add_argument("--time-budget-minutes", type=float, default=50.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="weekly_spy_dehb_real_500_parallel_1h_momentum_trend")
    parser.add_argument("--top-rows-per-stage", type=int, default=500)
    parser.add_argument("--random-seed", type=int, default=9102601)
    parser.add_argument("--train-start", default="1995-01-01")
    parser.add_argument("--train-end", default="2010-12-31")
    parser.add_argument("--validation-start", default="2011-01-01")
    parser.add_argument("--validation-end", default="2020-12-31")
    parser.add_argument("--locked-start", default="2021-01-01")
    parser.add_argument("--forbid-long-spy", action="store_true")
    parser.add_argument("--enable-search-quality", action="store_true")
    parser.add_argument("--feature-family-mode", choices=("none", "quality_stage"), default="none")
    parser.add_argument("--require-feature-data-from-year", type=int, default=None)
    parser.add_argument("--min-feature-weeks-per-year", type=int, default=26)
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()

    started_epoch = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    config = SP500WeeklyHedgeConfig(
        run_id=str(args.file_prefix),
        top_rows_per_stage=int(args.top_rows_per_stage),
        random_seed=int(args.random_seed),
        train_start=str(args.train_start),
        train_end=str(args.train_end),
        validation_start=str(args.validation_start),
        validation_end=str(args.validation_end),
        locked_start=str(args.locked_start),
        allow_late_entry=True,
        max_leverage=1.0,
        max_assets_per_candidate=1,
        exclude_asset_groups=("crypto_spot", "equity_single_name"),
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_audit: dict[str, Any]
    if args.synthetic_smoke:
        dataset = _synthetic_dataset()
        source_audit = {"available": True, "source": "synthetic_smoke", "locked_opened": False}
    else:
        dataset, source_audit = load_dataset(config)
    filtered, audit = _spy_momentum_trend_dataset(
        dataset,
        source_audit,
        require_feature_data_from_year=args.require_feature_data_from_year,
        min_feature_weeks_per_year=int(args.min_feature_weeks_per_year),
    )
    if args.feature_family_mode == "quality_stage":
        filtered, family_audit = _feature_family_dataset(filtered, int(args.stage))
        audit.update(family_audit)
    quality_config = SearchQualityConfig(
        history_start_year=int(args.require_feature_data_from_year or 1995),
        min_feature_weeks_per_year=int(args.min_feature_weeks_per_year),
    )
    row_filter = _quality_row_filter(quality_config, forbid_long_spy=bool(args.forbid_long_spy)) if args.enable_search_quality or args.forbid_long_spy else None
    rows, meta, _ = run_stage(
        config,
        stage=int(args.stage),
        total_stages=int(args.total_stages),
        time_budget_minutes=float(args.time_budget_minutes),
        wave=int(args.wave),
        total_waves=int(args.total_waves),
        dataset=filtered,
        spec_transform=_quality_spec_transform if args.forbid_long_spy else None,
        row_filter=row_filter,
    )
    for row in rows:
        row["assets"] = "SPY"
        row["asset_count"] = 1
        row["max_leverage"] = 1.0
        row["spy_only"] = True
        row["feature_filter"] = "momentum_trend_only"
        row["crypto_used"] = False
        row["no_long_spy"] = bool(args.forbid_long_spy)
        row["exposure_policy"] = "short_or_cash_spy" if args.forbid_long_spy else "unrestricted_long_short_spy"
        if args.enable_search_quality:
            _annotate_quality_outputs(row, quality_config)
    stem = f"{args.file_prefix}_wave_{int(args.wave)}_stage_{int(args.stage)}"
    pd.DataFrame(rows).to_csv(output_dir / f"{stem}.csv", index=False)
    meta.update(
        {
            "objective": "maximize_positive_strategy_return_on_spy_down_weeks_and_non_negative_mean_on_spy_up_weeks",
            "assets_used": ["SPY"],
            "spy_only": True,
            "feature_filter": "momentum_trend_only",
            "crypto_used": False,
            "max_leverage": 1.0,
            "no_long_spy": bool(args.forbid_long_spy),
            "exposure_policy": "short_or_cash_spy" if args.forbid_long_spy else "unrestricted_long_short_spy",
            "search_quality_enabled": bool(args.enable_search_quality),
            "feature_family_mode": str(args.feature_family_mode),
        }
    )
    (output_dir / f"{stem}_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    audit.update(
        {
            "no_long_spy": bool(args.forbid_long_spy),
            "exposure_policy": "short_or_cash_spy" if args.forbid_long_spy else "unrestricted_long_short_spy",
            "search_quality_enabled": bool(args.enable_search_quality),
            "require_feature_data_from_year": args.require_feature_data_from_year,
            "min_feature_weeks_per_year": int(args.min_feature_weeks_per_year),
        }
    )
    (output_dir / f"{stem}_feature_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    _write_job_meta(output_dir, args, started_epoch=started_epoch, started_iso=started_iso, rows=len(rows))
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


def _spy_momentum_trend_dataset(
    dataset: dict[str, Any],
    source_audit: dict[str, Any],
    *,
    require_feature_data_from_year: int | None = None,
    min_feature_weeks_per_year: int = 26,
) -> tuple[dict[str, Any], dict[str, Any]]:
    features = [str(name) for name in dataset.get("feature_names", ())]
    allowed = [name for name in features if _feature_allowed(name)]
    forbidden_found = [name for name in features if any(token in name.lower() for token in FORBIDDEN_FEATURE_TOKENS)]
    if not allowed:
        raise ValueError("no SPY momentum/trend features available after filter")
    train_rets = pd.DataFrame(dataset["train_asset_returns"]).copy()
    valid_rets = pd.DataFrame(dataset["valid_asset_returns"]).copy()
    if "SPY" not in train_rets.columns or "SPY" not in valid_rets.columns:
        raise ValueError("SPY asset returns are required for SPY-only run")
    train_x_source = pd.DataFrame(dataset["train_x"])
    valid_x_source = pd.DataFrame(dataset["valid_x"])
    train_attrs = getattr(dataset["train_x"], "attrs", {})
    valid_attrs = getattr(dataset["valid_x"], "attrs", {})
    train_availability = train_attrs.get("availability_mask") if isinstance(train_attrs.get("availability_mask"), pd.DataFrame) else train_x_source.notna()
    valid_availability = valid_attrs.get("availability_mask") if isinstance(valid_attrs.get("availability_mask"), pd.DataFrame) else valid_x_source.notna()
    history_rejected: list[str] = []
    if require_feature_data_from_year is not None:
        allowed, history_rejected = filter_features_by_history(
            tuple(allowed),
            pd.DataFrame(train_availability),
            start_year=int(require_feature_data_from_year),
            min_weeks_per_year=int(min_feature_weeks_per_year),
        )
        if not allowed:
            raise ValueError("no SPY momentum/trend features available with required 1995+ coverage")
    train_x = train_x_source.loc[:, allowed].copy()
    valid_x = valid_x_source.loc[:, allowed].copy()
    train_x.attrs["availability_mask"] = pd.DataFrame(train_availability).loc[:, allowed]
    valid_x.attrs["availability_mask"] = pd.DataFrame(valid_availability).loc[:, allowed]
    filtered = dict(dataset)
    filtered.update(
        {
            "train_x": train_x,
            "valid_x": valid_x,
            "train_asset_returns": train_rets.loc[:, ["SPY"]],
            "valid_asset_returns": valid_rets.loc[:, ["SPY"]],
            "feature_names": tuple(train_x.columns),
            "asset_symbols": ("SPY",),
        }
    )
    audit = {
        "available": True,
        "source_audit": source_audit,
        "feature_filter": "momentum_trend_only",
        "feature_columns_source_count": int(len(features)),
        "feature_columns_used_count": int(len(train_x.columns)),
        "feature_columns_used_names": list(train_x.columns),
        "feature_columns_rejected_count": int(len(features) - len(allowed)),
        "feature_columns_history_rejected_count": int(len(history_rejected)),
        "feature_columns_history_rejected_names": history_rejected,
        "forbidden_features_found": forbidden_found,
        "require_feature_data_from_year": require_feature_data_from_year,
        "min_feature_weeks_per_year": int(min_feature_weeks_per_year),
        "feature_columns_rejected_history_count": int(len(history_rejected)),
        "feature_columns_rejected_history_names": history_rejected,
        "assets_used": ["SPY"],
        "assets_used_count": 1,
        "spy_only": True,
        "crypto_used": False,
        "locked_opened": False,
    }
    _fail_if_invalid_filtered_dataset(filtered, audit)
    return filtered, audit

def _feature_family_dataset(dataset: dict[str, Any], stage: int) -> tuple[dict[str, Any], dict[str, Any]]:
    family = QUALITY_FAMILIES[int(stage) % len(QUALITY_FAMILIES)]
    features = [str(name) for name in dataset.get("feature_names", ())]
    if family == "mixed":
        selected = features
    else:
        selected = [feature for feature in features if _feature_bucket(feature) == family]
    if not selected:
        selected = features
        family = "mixed_fallback"

    train_x = pd.DataFrame(dataset["train_x"]).loc[:, selected].copy()
    valid_x = pd.DataFrame(dataset["valid_x"]).loc[:, selected].copy()
    train_availability = getattr(dataset["train_x"], "attrs", {}).get("availability_mask")
    valid_availability = getattr(dataset["valid_x"], "attrs", {}).get("availability_mask")
    if isinstance(train_availability, pd.DataFrame):
        train_x.attrs["availability_mask"] = train_availability.loc[:, selected]
    if isinstance(valid_availability, pd.DataFrame):
        valid_x.attrs["availability_mask"] = valid_availability.loc[:, selected]

    filtered = dict(dataset)
    filtered.update({"train_x": train_x, "valid_x": valid_x, "feature_names": tuple(selected)})
    return filtered, {"feature_family": family, "feature_family_mode": "quality_stage", "feature_family_count": int(len(selected))}


def _quality_spec_transform(spec: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(spec)
    transformed["exposure_policy"] = "short_or_cash_spy"
    return transformed


def _feature_bucket(feature: str) -> str:
    lower = str(feature).lower()
    if "vix" in lower:
        return "vix_trend"
    if lower.startswith("spy__ret"):
        return "spy_momentum"
    if lower.startswith("spy__ma_gap") or lower.startswith("spy__drawdown"):
        return "spy_trend_drawdown"
    if "__vol_" in lower or "__corr_spy" in lower or "__beta_spy" in lower:
        return "trend_volatility"
    if "__ret_" in lower:
        return "relative_etf"
    return "mixed"


def _quality_row_filter(config: SearchQualityConfig, *, forbid_long_spy: bool):
    state = SearchQualityState(config)

    def _filter(row: dict[str, Any]) -> tuple[bool, str]:
        _annotate_quality_outputs(row, config)
        if forbid_long_spy:
            row["no_long_spy"] = True
            row["exposure_policy"] = "short_or_cash_spy"
            if int(row.get("long_spy_weeks_train", 0) or 0) > 0:
                return False, "long_spy_in_train"
            if int(row.get("long_spy_weeks_validation", 0) or 0) > 0:
                return False, "long_spy_in_validation"
            if float(row.get("max_spy_position_train", 0.0) or 0.0) > 1e-12:
                return False, "positive_spy_position_train"
            if float(row.get("max_spy_position_validation", 0.0) or 0.0) > 1e-12:
                return False, "positive_spy_position_validation"

        prune = early_prune_reason(
            {
                "periods": row.get("effective_train_weeks", 0),
                "train_cagr": row.get("train_cagr", 0.0),
                "train_mdd": row.get("train_max_drawdown", 0.0),
                "train_down_positive_pct": row.get("train_spy_down_positive_pct", 0.0),
            },
            config,
        )
        if prune:
            row["quality_rejection_reason"] = prune
            return False, prune

        decision = state.accept(
            {
                "candidate_id": row.get("candidate_id"),
                "method": row.get("method"),
                "features": row.get("features"),
                "assets": row.get("assets"),
                "asset_weights": row.get("asset_weights"),
                "rules": row.get("rule"),
            },
            _returns_series(row.get("train_returns_json")),
        )
        if not decision.accepted:
            row["duplicate_of"] = decision.duplicate_of
            return False, decision.reason

        row["raw_train_score"] = row.get("train_score", 0.0)
        row["quality_train_score"] = robust_train_score(row, config)
        row["train_score"] = float(row.get("train_score", 0.0) or 0.0) + 10.0 * float(row["quality_train_score"])
        return True, ""

    return _filter


def _annotate_quality_outputs(row: dict[str, Any], config: SearchQualityConfig) -> None:
    train = _returns_series(row.get("train_returns_json"))
    validation = _returns_series(row.get("validation_returns_json"))
    train_soft = simple_soft_robustness(train, config)
    validation_soft = simple_soft_robustness(validation, config)
    row.update({f"train_{key}": value for key, value in train_soft.items()})
    row.update({f"validation_{key}": value for key, value in validation_soft.items()})
    row["simple_robust_pass"] = bool(train_soft["soft_robust_pass"] and validation_soft["soft_robust_pass"])
    row["return_fingerprint"] = _return_fingerprint(train)
    row["duplicate_group_id"] = str(row["return_fingerprint"])
    row["duplicate_representative"] = True
    row["portfolio_eligible"] = bool(row["simple_robust_pass"])


def _returns_series(payload: Any) -> pd.Series:
    if isinstance(payload, pd.Series):
        return pd.to_numeric(payload, errors="coerce").dropna().reset_index(drop=True)
    if isinstance(payload, str):
        try:
            values = json.loads(payload)
        except json.JSONDecodeError:
            values = []
    elif isinstance(payload, list):
        values = payload
    else:
        values = []
    return pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def _return_fingerprint(series: pd.Series) -> str:
    values = np.round(pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float), 8)
    return hashlib.sha256(values.tobytes()).hexdigest()[:16]


def _feature_allowed(name: str) -> bool:
    lower = name.lower()
    if any(token in lower for token in FORBIDDEN_FEATURE_TOKENS):
        return False
    if any(token in lower for token in CRYPTO_TOKENS):
        return False
    if name.endswith(ALLOWED_SUFFIXES):
        return True
    if lower.startswith("macro__vix") and ("__chg_4w" in lower or "__chg_13w" in lower):
        return True
    return False


def _fail_if_invalid_filtered_dataset(dataset: dict[str, Any], audit: dict[str, Any]) -> None:
    assets = tuple(str(asset) for asset in dataset.get("asset_symbols", ()))
    if assets != ("SPY",):
        raise ValueError(f"SPY-only run expected asset_symbols=('SPY',), got {assets}")
    features = tuple(str(feature) for feature in dataset.get("feature_names", ()))
    bad = [feature for feature in features if not _feature_allowed(feature)]
    if bad:
        raise ValueError(f"non momentum/trend features leaked into catalog: {bad[:10]}")
    if audit.get("forbidden_features_found"):
        leaked_used = [feature for feature in audit["forbidden_features_found"] if feature in features]
        if leaked_used:
            raise ValueError(f"forbidden features leaked into used catalog: {leaked_used[:10]}")


def _synthetic_dataset() -> dict[str, object]:
    idx = pd.date_range("2020-01-03", periods=160, freq="W-FRI")
    spy = np.resize(np.array([0.03, -0.04, 0.02, -0.03], dtype=float), len(idx))
    qqq = spy * 1.2
    asset_returns = pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)
    features = pd.DataFrame(
        {
            "SPY__ret_1w": spy,
            "SPY__ma_gap_10w": np.resize(np.array([0.02, -0.03, 0.01, -0.02]), len(idx)),
            "QQQ__ret_13w": qqq,
            "macro__VIXCLS__chg_4w": np.where(spy < 0.0, 1.0, -1.0),
            "macro__UNRATE__level": np.linspace(4.0, 5.0, len(idx)),
            "BTCUSDT__ret_1w": qqq,
        },
        index=idx,
    )
    return {
        "train_x": features.iloc[:120],
        "valid_x": features.iloc[120:],
        "train_asset_returns": asset_returns.iloc[:120],
        "valid_asset_returns": asset_returns.iloc[120:],
        "train_spy_returns": asset_returns["SPY"].iloc[:120].to_numpy(dtype=float),
        "valid_spy_returns": asset_returns["SPY"].iloc[120:].to_numpy(dtype=float),
        "train_index": pd.DatetimeIndex(idx[:120]),
        "valid_index": pd.DatetimeIndex(idx[120:]),
        "feature_names": tuple(features.columns),
        "asset_symbols": ("SPY", "QQQ"),
    }


def _write_job_meta(output_dir: Path, args: argparse.Namespace, *, started_epoch: float, started_iso: str, rows: int) -> None:
    ended_epoch = time.time()
    payload = {
        "method": "dehb_real",
        "stage": int(args.stage),
        "wave": int(args.wave),
        "started_epoch": float(started_epoch),
        "ended_epoch": float(ended_epoch),
        "started_at": started_iso,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": float(ended_epoch - started_epoch),
        "rows": int(rows),
    }
    (output_dir / "job_meta.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
