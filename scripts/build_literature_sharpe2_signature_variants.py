from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


SUPPORTED_SIGNALS = {
    "momentum_trend",
    "reversal_mean_reversion",
    "volatility_signal",
    "carry_yield",
    "liquidity",
    "macro_inflation",
    "macro_growth_unemployment",
    "geopolitical_policy_uncertainty",
    "value_quality_factor",
    "ml_forecast",
    "correlation_spillover",
    "regime_switching",
    "credit_spread_signal",
    "sentiment_news",
    "portfolio_optimization",
}
SUPPORTED_ACTIONS = {
    "forecast_rank_template",
    "long_short_cross_section",
    "hedge_safe_haven",
    "market_timing",
    "rotation_allocation",
    "template_relationship",
}
SUPPORTED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual", "unspecified"}
MULTI_SYMBOL_ASSETS = {"equity_index", "sector", "bonds_rates", "credit", "commodities", "fx", "multi_asset", "macro", "volatility"}

LOOKBACKS_BY_FREQUENCY = {
    "daily": ("5d", "10d", "21d", "42d", "63d", "126d", "252d"),
    "weekly": ("4w", "8w", "13w", "26w", "39w", "52w", "104w"),
    "monthly": ("1m", "2m", "3m", "6m", "9m", "12m", "18m", "24m", "36m"),
    "quarterly": ("2q", "4q", "8q", "12q"),
    "annual": ("2y", "3y", "5y"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build paper-based Sharpe2 signature variants.")
    parser.add_argument("--source", default="config/literature_strategy_signatures_9419.csv")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--max-variants", type=int, default=80_000)
    parser.add_argument("--exclude-asset-bucket", action="append", default=[])
    args = parser.parse_args()

    frame = pd.read_csv(args.source)
    variants = build_variants(
        frame,
        max_variants=int(args.max_variants),
        exclude_asset_buckets=set(map(str, args.exclude_asset_bucket or [])),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    variants.to_csv(out, index=False)
    summary = {
        "source": str(args.source),
        "source_rows": int(len(frame)),
        "output_rows": int(len(variants)),
        "max_variants": int(args.max_variants),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "paper_based": True,
        "excluded_asset_buckets": list(map(str, args.exclude_asset_bucket or [])),
    }
    summary_path = Path(args.summary) if args.summary else out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_variants(
    frame: pd.DataFrame,
    *,
    max_variants: int = 80_000,
    exclude_asset_buckets: set[str] | None = None,
) -> pd.DataFrame:
    required = {
        "signature_hash",
        "distinct_strategy_signature",
        "primary_family",
        "asset_bucket",
        "signal_bucket",
        "action_bucket",
        "frequency_bucket",
        "parameter_bucket",
        "example_study_id",
        "example_idea_id",
        "example_title",
        "exact_rows",
        "template_rows",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"source signatures missing columns: {missing}")

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    excluded = exclude_asset_buckets or set()
    for _, source in frame.iterrows():
        signal = str(source.get("signal_bucket") or "")
        action = str(source.get("action_bucket") or "")
        frequency = str(source.get("frequency_bucket") or "")
        asset = str(source.get("asset_bucket") or "")
        if asset in excluded:
            continue
        if signal not in SUPPORTED_SIGNALS or action not in SUPPORTED_ACTIONS or frequency not in SUPPORTED_FREQUENCIES:
            continue
        for freq in frequency_variants(frequency):
            for variant_action in action_variants(action, asset):
                for lookback in lookback_variants(str(source.get("parameter_bucket") or ""), freq):
                    row = variant_row(source.to_dict(), freq, variant_action, lookback)
                    sig = str(row["signature_hash"])
                    if sig in seen:
                        continue
                    seen.add(sig)
                    rows.append(row)
                    if len(rows) >= max_variants:
                        return pd.DataFrame(rows)
    if not rows:
        raise ValueError("variant builder produced zero rows")
    return pd.DataFrame(rows)


def frequency_variants(frequency: str) -> tuple[str, ...]:
    if frequency == "unspecified":
        return ("monthly", "weekly")
    return (frequency,)


def action_variants(action: str, asset_bucket: str) -> tuple[str, ...]:
    variants = [action]
    if asset_bucket in MULTI_SYMBOL_ASSETS:
        variants.extend(["forecast_rank_template", "long_short_cross_section", "rotation_allocation"])
    if asset_bucket in {"equity_index", "multi_asset", "macro", "volatility", "bonds_rates", "credit"}:
        variants.extend(["market_timing", "hedge_safe_haven"])
    return tuple(dict.fromkeys(variants))


def lookback_variants(parameter_bucket: str, frequency: str) -> tuple[str, ...]:
    existing = str(parameter_bucket or "").strip()
    defaults = LOOKBACKS_BY_FREQUENCY.get(frequency, ("12m",))
    if existing and existing != "no_explicit_lookback":
        return tuple(dict.fromkeys((existing, *defaults)))
    return defaults


def variant_row(source: dict[str, object], frequency: str, action: str, lookback: str) -> dict[str, object]:
    exact_rows = int(float(source.get("exact_rows", 0) or 0))
    template_rows = int(float(source.get("template_rows", 0) or 0))
    source_exactness = str(source.get("source_exactness") or ("exact_source" if exact_rows > 0 else "template_only"))
    family = str(source.get("primary_family") or "")
    asset = str(source.get("asset_bucket") or "")
    signal = str(source.get("signal_bucket") or "")
    variant_key = "|".join([str(source.get("signature_hash") or ""), frequency, action, lookback])
    variant_hash = hashlib.sha256(variant_key.encode("utf-8")).hexdigest()[:16]
    signature = "|".join([family, asset, signal, action, frequency, lookback])
    source_ref = {
        "source_signature_hash": str(source.get("signature_hash") or ""),
        "source_study_id": str(source.get("example_study_id") or ""),
        "source_idea_id": str(source.get("example_idea_id") or ""),
        "variant_frequency": frequency,
        "variant_action": action,
        "variant_lookback": lookback,
        "paper_based": True,
    }
    return {
        "signature_hash": variant_hash,
        "distinct_strategy_signature": signature,
        "rows": int(float(source.get("rows", 1) or 1)),
        "exact_rows": exact_rows,
        "template_rows": template_rows,
        "primary_family": family,
        "asset_bucket": asset,
        "signal_bucket": signal,
        "action_bucket": action,
        "frequency_bucket": frequency,
        "parameter_bucket": lookback,
        "example_study_id": str(source.get("example_study_id") or ""),
        "example_idea_id": str(source.get("example_idea_id") or ""),
        "example_title": str(source.get("example_title") or ""),
        "source_text_ref": json.dumps(source_ref, sort_keys=True),
        "rule_summary": f"Paper signature variant: {signature}",
        "fidelity_caveat": "Paper-derived Aurora variant; not an exact paper replication unless separately proven.",
        "source_exactness": source_exactness,
        "paper_exact_replication_claimed": False,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
