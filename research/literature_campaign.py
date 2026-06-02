"""Campaign layer for literature-to-Aurora strategy backtests.

The campaign layer is intentionally conservative. It turns paper evidence into
the existing literature-strategy signature format only when a minimum rule
contract is satisfied, then delegates actual backtesting to
``literature_strategy_backtest``.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml


SUPPORTED_EXACTNESS = {
    "exact_replicable",
    "proxy_replicable",
    "template_replicable",
}
REQUIRED_RULE_FIELDS = ("formula", "universe", "direction", "frequency")
DEFAULT_CHUNKS = 180
DEFAULT_MAX_PARALLEL = 180


@dataclass(frozen=True)
class LiteratureCampaignConfig:
    """Validated campaign configuration."""

    raw: dict[str, Any]
    path: str

    @property
    def campaign_id(self) -> str:
        return str(self.raw["campaign_id"])

    @property
    def train_start(self) -> str:
        return str(self.raw["backtest"]["train_start"])

    @property
    def train_end(self) -> str:
        return str(self.raw["backtest"]["train_end"])

    @property
    def validation_start(self) -> str:
        return str(self.raw["backtest"]["validation_start"])

    @property
    def validation_end(self) -> str:
        return str(self.raw["backtest"]["validation_end"])

    @property
    def locked_start(self) -> str:
        return str(self.raw["rules"]["locked_start"])

    @property
    def chunks(self) -> int:
        return int(self.raw.get("github", {}).get("chunks", DEFAULT_CHUNKS))

    @property
    def max_parallel(self) -> int:
        return int(self.raw.get("github", {}).get("max_parallel", DEFAULT_MAX_PARALLEL))

    @property
    def require_effective_start(self) -> str:
        return str(self.raw.get("rules", {}).get("require_effective_start_lte", ""))


def load_campaign_config(path: str | Path) -> LiteratureCampaignConfig:
    """Load and validate a literature campaign YAML file."""

    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("campaign config must be a YAML mapping")
    _validate_campaign(raw)
    return LiteratureCampaignConfig(raw=raw, path=str(config_path))


def build_campaign_inputs(config: LiteratureCampaignConfig) -> dict[str, pd.DataFrame | dict[str, Any]]:
    """Build studies, rule extraction rows and strategy specs for a campaign."""

    exactness = _load_local_exactness(config)
    studies = _campaign_studies(exactness)
    rules = _campaign_rules(config, exactness)
    specs = _campaign_specs(config, rules)
    unsupported = specs[specs["status"] == "unsupported"].copy()
    signatures = specs[specs["status"] == "ready"].drop(columns=["status", "unsupported_reason"])
    summary = {
        "campaign_id": config.campaign_id,
        "studies": int(len(studies)),
        "rule_rows": int(len(rules)),
        "strategy_specs": int(len(signatures)),
        "unsupported": int(len(unsupported)),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "external_search_requested": bool(config.raw.get("sources", {}).get("search_external", False)),
        "external_queries": list(config.raw.get("sources", {}).get("external_queries", []) or []),
    }
    return {
        "studies": studies,
        "rules": rules,
        "specs": signatures.reset_index(drop=True),
        "unsupported": unsupported.reset_index(drop=True),
        "summary": summary,
    }


def write_campaign_inputs(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Write campaign discovery/rule/spec artifacts and return the summary."""

    config = load_campaign_config(config_path)
    built = build_campaign_inputs(config)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    studies = built["studies"]
    rules = built["rules"]
    specs = built["specs"]
    unsupported = built["unsupported"]
    assert isinstance(studies, pd.DataFrame)
    assert isinstance(rules, pd.DataFrame)
    assert isinstance(specs, pd.DataFrame)
    assert isinstance(unsupported, pd.DataFrame)
    studies.to_csv(out / "campaign_studies.csv", index=False)
    pd.DataFrame().to_csv(out / "campaign_pdf_status.csv", index=False)
    rules.to_csv(out / "campaign_rule_extraction.csv", index=False)
    specs.to_csv(out / "campaign_strategy_specs.csv", index=False)
    unsupported.to_csv(out / "campaign_unsupported.csv", index=False)
    summary = dict(built["summary"])
    summary.update({
        "strategy_specs_path": str(out / "campaign_strategy_specs.csv"),
        "unsupported_path": str(out / "campaign_unsupported.csv"),
    })
    (out / "campaign_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out / "campaign_audit.md").write_text(_audit_markdown(config, summary), encoding="utf-8")
    return summary


def campaign_to_backtest_config_kwargs(config: LiteratureCampaignConfig) -> dict[str, Any]:
    """Return kwargs compatible with LiteratureBacktestConfig."""

    return {
        "signatures_path": "",
        "train_start": config.train_start,
        "train_end": config.train_end,
        "validation_start": config.validation_start,
        "validation_end": config.validation_end,
        "locked_start": config.locked_start,
        "expected_signatures": 0,
    }


def _validate_campaign(raw: Mapping[str, Any]) -> None:
    required_top = {"campaign_id", "objective", "sources", "rules", "universe", "backtest", "ranking"}
    missing = sorted(required_top - set(raw))
    if missing:
        raise ValueError(f"campaign missing sections: {missing}")
    rules = _mapping(raw, "rules")
    backtest = _mapping(raw, "backtest")
    github = dict(raw.get("github", {}) or {})
    if bool(rules.get("locked_opened", True)):
        raise ValueError("campaign must keep rules.locked_opened=false")
    if int(rules.get("min_lag_days", 0)) < 1:
        raise ValueError("campaign must require min_lag_days >= 1")
    if not bool(backtest.get("choose_size_on_train_only", False)):
        raise ValueError("campaign must choose size on train only")
    if pd.Timestamp(str(backtest["validation_end"])) >= pd.Timestamp(str(rules["locked_start"])):
        raise ValueError("validation_end must be before locked_start")
    if str(rules.get("sp500_down_horizon", "")).strip() not in {"months", ""}:
        raise ValueError("campaign currently supports rules.sp500_down_horizon=months")
    require_start = str(rules.get("require_effective_start_lte", "")).strip()
    if require_start:
        if pd.Timestamp(require_start) > pd.Timestamp(str(backtest["train_start"])):
            raise ValueError("require_effective_start_lte must be <= train_start")
    if int(github.get("chunks", DEFAULT_CHUNKS)) <= 0:
        raise ValueError("github.chunks must be positive")
    if int(github.get("max_parallel", DEFAULT_MAX_PARALLEL)) <= 0:
        raise ValueError("github.max_parallel must be positive")
    if int(github.get("max_parallel", DEFAULT_MAX_PARALLEL)) > 256:
        raise ValueError("github.max_parallel must not exceed GitHub matrix max-parallel safety limit 256")
    primary_metric = str(_mapping(raw, "ranking").get("primary_metric", "")).strip()
    if primary_metric.startswith("train_"):
        return
    if primary_metric.startswith("validation_"):
        return
    raise ValueError("ranking.primary_metric must be a train_ or validation_ metric")


def _mapping(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"campaign section {key!r} must be a mapping")
    return dict(value)


def _load_local_exactness(config: LiteratureCampaignConfig) -> pd.DataFrame:
    sources = _mapping(config.raw, "sources")
    path = Path(str(sources.get("local_exactness_csv", "")))
    if not path.exists():
        raise FileNotFoundError(f"local_exactness_csv not found: {path}")
    frame = pd.read_csv(path)
    required = {
        "study_id",
        "idea_id",
        "strategy_family",
        "signal_formula",
        "asset_universe",
        "frequency",
        "position_rule",
        "exactness_status",
        "evidence_quote_refs",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"local exactness CSV missing columns: {missing}")
    return frame


def _campaign_studies(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        c
        for c in ["study_id", "idea_id", "strategy_family", "tradable_assets", "sample_period", "benchmark"]
        if c in frame.columns
    ]
    out = frame.loc[:, cols].drop_duplicates(subset=["study_id", "idea_id"]).reset_index(drop=True)
    return out


def _campaign_rules(config: LiteratureCampaignConfig, frame: pd.DataFrame) -> pd.DataFrame:
    rules = _mapping(config.raw, "rules")
    allow_status = set()
    if bool(rules.get("allow_exact", True)):
        allow_status.add("exact_replicable")
    if bool(rules.get("allow_proxy", True)):
        allow_status.add("proxy_replicable")
    if bool(rules.get("allow_template", False)):
        allow_status.add("template_replicable")
    if not allow_status:
        raise ValueError("campaign allows no replicable status")

    work = frame.copy()
    status_col = "exactness_status_after_review" if "exactness_status_after_review" in work.columns else "exactness_status"
    work["campaign_exactness_status"] = work[status_col].fillna(work["exactness_status"]).astype(str)
    work["campaign_rule_status"] = work["campaign_exactness_status"].map(
        lambda status: status if status in allow_status else "unsupported"
    )
    work["unsupported_reason"] = ""
    work.loc[work["campaign_rule_status"].eq("unsupported"), "unsupported_reason"] = (
        "exactness_status_not_allowed"
    )
    work["evidence_ok"] = work.apply(_has_required_evidence, axis=1)
    require_evidence = bool(rules.get("require_full_text_evidence", True))
    if require_evidence:
        mask = work["campaign_rule_status"].ne("unsupported") & ~work["evidence_ok"]
        work.loc[mask, "campaign_rule_status"] = "unsupported"
        work.loc[mask, "unsupported_reason"] = "missing_required_evidence"
    return work.reset_index(drop=True)


def _campaign_specs(config: LiteratureCampaignConfig, rules: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in rules.iterrows():
        base = _row_to_signature(config, row.to_dict())
        if str(row.get("campaign_rule_status")) == "unsupported":
            base["status"] = "unsupported"
            base["unsupported_reason"] = str(row.get("unsupported_reason") or "unsupported_rule")
        else:
            unsupported_reason = _filter_spec(config, base)
            base["status"] = "unsupported" if unsupported_reason else "ready"
            base["unsupported_reason"] = unsupported_reason
        if base["signature_hash"] in seen:
            continue
        seen.add(base["signature_hash"])
        rows.append(base)
    return pd.DataFrame(rows)


def _row_to_signature(config: LiteratureCampaignConfig, row: dict[str, Any]) -> dict[str, Any]:
    family = str(row.get("strategy_family") or "literature")
    text = " ".join(
        str(row.get(col) or "")
        for col in [
            "strategy_family",
            "signal_formula",
            "asset_universe",
            "tradable_assets",
            "frequency",
            "position_rule",
            "thresholds",
            "lookback_windows",
        ]
    )
    asset_bucket = _asset_bucket(text)
    signal_bucket = _signal_bucket(family, text)
    action_bucket = _action_bucket(text)
    frequency_bucket = _frequency_bucket(str(row.get("frequency") or text))
    parameter_bucket = _parameter_bucket(str(row.get("lookback_windows") or row.get("thresholds") or ""))
    signature = "|".join([family, asset_bucket, signal_bucket, action_bucket, frequency_bucket, parameter_bucket])
    signature_hash = hashlib.sha256(
        f"{config.campaign_id}|{signature}|{row.get('study_id')}|{row.get('idea_id')}".encode("utf-8")
    ).hexdigest()[:16]
    exactness = str(row.get("campaign_exactness_status") or row.get("exactness_status") or "")
    source_exactness = "exact_source" if exactness == "exact_replicable" else "proxy_or_template_source"
    return {
        "signature_hash": signature_hash,
        "distinct_strategy_signature": signature,
        "rows": 1,
        "exact_rows": 1 if exactness == "exact_replicable" else 0,
        "template_rows": 1 if exactness == "template_replicable" else 0,
        "primary_family": family,
        "asset_bucket": asset_bucket,
        "signal_bucket": signal_bucket,
        "action_bucket": action_bucket,
        "frequency_bucket": frequency_bucket,
        "parameter_bucket": parameter_bucket,
        "example_study_id": str(row.get("study_id") or ""),
        "example_idea_id": str(row.get("idea_id") or ""),
        "example_title": str(row.get("tradable_assets") or row.get("study_title") or ""),
        "source_exactness": source_exactness,
        "source_text_ref": str(row.get("evidence_quote_refs") or ""),
        "rule_summary": _short_rule(row),
        "fidelity_caveat": _fidelity_caveat(exactness),
        "paper_exact_replication_claimed": False,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }


def _filter_spec(config: LiteratureCampaignConfig, spec: dict[str, Any]) -> str:
    universe = _mapping(config.raw, "universe")
    allow_assets = {str(v).lower() for v in universe.get("allow_assets", []) or []}
    forbid_assets = {str(v).lower() for v in universe.get("forbid_assets", []) or []}
    asset_tag = _asset_tag(spec["asset_bucket"])
    if allow_assets and asset_tag.lower() not in allow_assets:
        return "asset_not_allowed_by_campaign"
    if asset_tag.lower() in forbid_assets:
        return "asset_forbidden_by_campaign"
    if spec["frequency_bucket"] == "intraday":
        return "unsupported_frequency_intraday"
    if spec["signal_bucket"] == "unsupported":
        return "unsupported_no_signal_mapping"
    return ""


def _has_required_evidence(row: pd.Series) -> bool:
    raw = row.get("evidence_quote_refs", "")
    try:
        evidence = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except json.JSONDecodeError:
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}
    text_blob = " ".join(str(row.get(col) or "") for col in ["signal_formula", "asset_universe", "position_rule", "frequency"])
    found = {
        "formula": _present(evidence.get("formula")) or _present(row.get("signal_formula")),
        "universe": _present(evidence.get("universe")) or _present(row.get("asset_universe")),
        "direction": _present(evidence.get("direction")) or _present(row.get("position_rule")),
        "frequency": _present(evidence.get("frequency")) or _present(row.get("frequency")) or _frequency_bucket(text_blob) != "unspecified",
    }
    return all(found[field] for field in REQUIRED_RULE_FIELDS)


def _present(value: object) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(str(value).strip())


def _asset_bucket(text: str) -> str:
    t = _norm(text)
    if any(token in t for token in ["crypto", "bitcoin", "btc", "ethereum"]):
        return "crypto"
    if any(token in t for token in ["currency", "forex", "fx", "dollar", "exchange rate"]):
        return "fx"
    if any(token in t for token in ["commodity", "gold", "oil", "silver"]):
        return "commodities"
    if any(token in t for token in ["bond", "treasury", "yield", "rates", "fixed income"]):
        return "bonds_rates"
    if any(token in t for token in ["sector", "industry"]):
        return "sector"
    if any(token in t for token in ["multi asset", "asset allocation", "portfolio"]):
        return "multi_asset"
    return "equity_index"


def _asset_tag(asset_bucket: str) -> str:
    return {
        "equity_index": "ETF",
        "sector": "ETF",
        "bonds_rates": "rates",
        "credit": "rates",
        "commodities": "ETF",
        "fx": "ETF",
        "crypto": "crypto",
        "multi_asset": "ETF",
        "macro": "macro",
        "volatility": "volatility_index",
    }.get(asset_bucket, asset_bucket)


def _signal_bucket(family: str, text: str) -> str:
    t = _norm(f"{family} {text}")
    if any(token in t for token in ["momentum", "trend", "moving average", "time series"]):
        return "momentum_trend"
    if any(token in t for token in ["reversal", "mean reversion", "contrarian"]):
        return "reversal_mean_reversion"
    if any(token in t for token in ["volatility", "vix", "skew", "variance", "crash", "tail"]):
        return "volatility_signal"
    if any(token in t for token in ["carry", "yield", "term premium"]):
        return "carry_yield"
    if "inflation" in t:
        return "macro_inflation"
    if any(token in t for token in ["unemployment", "growth", "business cycle"]):
        return "macro_growth_unemployment"
    if "credit spread" in t:
        return "credit_spread_signal"
    if "liquidity" in t:
        return "liquidity"
    if any(token in t for token in ["value", "quality", "factor"]):
        return "value_quality_factor"
    if any(token in t for token in ["correlation", "spillover"]):
        return "correlation_spillover"
    if any(token in t for token in ["machine learning", "forecast", "predict"]):
        return "ml_forecast"
    return "unsupported"


def _action_bucket(text: str) -> str:
    t = _norm(text)
    if "long short" in t or ("long" in t and "short" in t):
        return "long_short_cross_section"
    if any(token in t for token in ["hedge", "safe haven", "protect"]):
        return "hedge_safe_haven"
    if any(token in t for token in ["market timing", "risk on", "risk off", "allocate"]):
        return "market_timing"
    if any(token in t for token in ["rotation", "rebalance", "portfolio"]):
        return "rotation_allocation"
    return "forecast_rank_template"


def _frequency_bucket(text: str) -> str:
    t = _norm(text)
    if "intraday" in t or "minute" in t or "hour" in t:
        return "intraday"
    if "daily" in t or "day" in t:
        return "daily"
    if "weekly" in t or "week" in t:
        return "weekly"
    if "quarter" in t:
        return "quarterly"
    if "annual" in t or "yearly" in t:
        return "annual"
    if "monthly" in t or "month" in t:
        return "monthly"
    return "unspecified"


def _parameter_bucket(text: str) -> str:
    t = _norm(text)
    match = re.search(r"\b(\d{1,3})\s*(day|week|month|year)", t)
    if match:
        return f"{match.group(1)}{match.group(2)[0]}"
    return "no_explicit_lookback"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _short_rule(row: Mapping[str, Any]) -> str:
    parts = [
        str(row.get("signal_formula") or "").strip(),
        str(row.get("position_rule") or "").strip(),
        str(row.get("frequency") or "").strip(),
    ]
    return " | ".join(part for part in parts if part)[:500]


def _fidelity_caveat(exactness: str) -> str:
    if exactness == "exact_replicable":
        return "Fuente marcada como exact_replicable por pipeline de texto; backtest Aurora sigue siendo verificacion propia."
    if exactness == "proxy_replicable":
        return "Proxy replicable, no replica exacta del paper."
    if exactness == "template_replicable":
        return "Plantilla testeable inspirada en el paper, no replica exacta."
    return "No se debe usar como replica."


def _audit_markdown(config: LiteratureCampaignConfig, summary: Mapping[str, Any]) -> str:
    return "\n".join([
        f"# Literature Campaign {config.campaign_id}",
        "",
        f"Objective: {config.raw.get('objective', '')}",
        "",
        f"- studies: {summary.get('studies')}",
        f"- rule rows: {summary.get('rule_rows')}",
        f"- strategy specs: {summary.get('strategy_specs')}",
        f"- unsupported: {summary.get('unsupported')}",
        "- locked_opened: false",
        "- validation_used_for_selection: false",
        "- paper_exact_replication_claimed: false by default",
        "",
    ])


__all__ = [
    "LiteratureCampaignConfig",
    "build_campaign_inputs",
    "campaign_to_backtest_config_kwargs",
    "load_campaign_config",
    "write_campaign_inputs",
]
