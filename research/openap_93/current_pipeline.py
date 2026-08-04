"""End-to-end current OpenAP 93 integration and auditable score outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import shutil
import time

import duckdb
import numpy as np
import pandas as pd

from aurora.research.openap_current_score import (
    calculate_scores,
    evidence_weight,
    signed_percentile,
)

from .accounting_pipeline import (
    ACCOUNTING_IMPLEMENTED_SIGNALS,
    calculate_accounting_signals,
)
from .advanced_accounting_pipeline import (
    ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS,
    calculate_advanced_accounting_signals,
)
from .event_pipeline import EVENT_IMPLEMENTED_SIGNALS, calculate_event_signals
from .market_pipeline import MARKET_IMPLEMENTED_SIGNALS, calculate_market_signals
from .quarterly_pipeline import (
    QUARTERLY_IMPLEMENTED_SIGNALS,
    calculate_quarterly_signals,
)
from .registry import REQUIRED_93, FidelityClass, SignalSpec
from .sources import PUBLIC_SOURCES


REQUIRED_SIGNAL_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "filed_at",
    "available_at",
    "retrieved_at",
    "value",
    "fidelity_class",
    "current_usable",
    "source_id",
    "source_url",
    "coverage_flag",
    "formula_id",
    "openap_script",
    "natural_frequency",
    "staleness_days",
    "is_current_for_natural_frequency",
    "observation_count",
    "reason_if_missing",
    "caveat",
)

IMPLEMENTED_SIGNALS = frozenset(
    ACCOUNTING_IMPLEMENTED_SIGNALS
    | ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS
    | EVENT_IMPLEMENTED_SIGNALS
    | MARKET_IMPLEMENTED_SIGNALS
    | QUARTERLY_IMPLEMENTED_SIGNALS
)

SOURCE_URLS = {source.source_id: source.probe_url for source in PUBLIC_SOURCES}
SOURCE_DOMAINS = {source.source_id: source.domain for source in PUBLIC_SOURCES}
SOURCE_LICENSES = {source.source_id: source.license for source in PUBLIC_SOURCES}
SOURCE_TERMS = {source.source_id: source.automation_status for source in PUBLIC_SOURCES}

FIDELITY_ORDER = {
    FidelityClass.EXACT.value: 0,
    FidelityClass.RECONSTRUCTED.value: 1,
    FidelityClass.VALIDATED_PROXY.value: 2,
    FidelityClass.UNVALIDATED_PROXY.value: 3,
    FidelityClass.STALE_REFERENCE_ONLY.value: 4,
    FidelityClass.UNAVAILABLE.value: 5,
}

CURRENT_USABLE_CLASSES = {
    FidelityClass.EXACT.value,
    FidelityClass.RECONSTRUCTED.value,
    FidelityClass.VALIDATED_PROXY.value,
}

SCORE_VARIANTS = {
    "score_strict_current": {
        FidelityClass.EXACT.value,
        FidelityClass.RECONSTRUCTED.value,
    },
    "score_max_current": CURRENT_USABLE_CLASSES,
    "score_research_all": CURRENT_USABLE_CLASSES
    | {FidelityClass.UNVALIDATED_PROXY.value},
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _staleness_limit(frequency: str) -> int:
    normalized = str(frequency).strip().lower()
    return {
        "daily": 10,
        "weekly": 21,
        "monthly": 70,
        "quarterly": 220,
        "annual": 760,
        "event": 760,
        "intraday": 3,
    }.get(normalized, 760)


def _find_database(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    matches = sorted(candidate.rglob("openap_current.duckdb"))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one openap_current.duckdb under {candidate}, found {len(matches)}"
        )
    return matches[0]


def _load_public_frames(normalized_dir: str | Path) -> dict[str, pd.DataFrame]:
    root = Path(normalized_dir)
    required = (
        "ff3_daily",
        "ff3_monthly",
        "liquidity_monthly",
        "vix_daily",
        "gnp_deflator",
        "signal_doc",
    )
    frames: dict[str, pd.DataFrame] = {}
    for name in required:
        path = root / f"{name}.parquet"
        if not path.exists():
            raise RuntimeError(f"Missing normalized public input: {path}")
        frames[name] = pd.read_parquet(path)
        if frames[name].empty:
            raise RuntimeError(f"Normalized public input is empty: {name}")
    return frames


def _load_base_frames(
    database: Path,
    formation_at: pd.Timestamp,
    universe_symbols: set[str] | None,
) -> dict[str, pd.DataFrame]:
    connection = duckdb.connect(str(database), read_only=True)
    try:
        master = connection.execute(
            "SELECT * FROM security_master WHERE ranking_eligible"
        ).fetchdf()
        if universe_symbols is not None:
            master = master.loc[master["symbol"].isin(universe_symbols)].copy()
        if master.empty:
            raise RuntimeError("No ranking-eligible securities remain in the universe")
        symbols = master["symbol"].astype(str).tolist()
        connection.register("selected_symbols", pd.DataFrame({"symbol": symbols}))
        prices = connection.execute(
            """
            SELECT p.* FROM prices_daily_clean p
            INNER JOIN selected_symbols s USING (symbol)
            WHERE p.date <= ?
            ORDER BY p.symbol, p.date
            """,
            [formation_at],
        ).fetchdf()
        concepts = connection.execute(
            """
            SELECT c.* FROM sec_concept_inputs_current c
            INNER JOIN selected_symbols s USING (symbol)
            WHERE c.available_at <= ?
            """,
            [formation_at],
        ).fetchdf()
        companyfacts = connection.execute(
            """
            SELECT f.*, m.symbol
            FROM sec_companyfacts f
            INNER JOIN security_master m USING (cik)
            INNER JOIN selected_symbols s ON s.symbol = m.symbol
            WHERE f.available_at <= ?
            """,
            [formation_at],
        ).fetchdf()
        submissions = connection.execute(
            """
            SELECT u.*
            FROM sec_submissions u
            INNER JOIN security_master m USING (cik)
            INNER JOIN selected_symbols s ON s.symbol = m.symbol
            WHERE u.accepted_at IS NOT NULL AND u.accepted_at <= ?
            """,
            [formation_at],
        ).fetchdf()
        features = connection.execute(
            """
            SELECT f.* FROM openap_features_current f
            INNER JOIN selected_symbols s USING (symbol)
            """
        ).fetchdf()
        metadata = connection.execute("SELECT * FROM selected_predictors").fetchdf()
    finally:
        connection.close()
    return {
        "master": master,
        "prices": prices,
        "concepts": concepts,
        "companyfacts": companyfacts,
        "submissions": submissions,
        "features": features,
        "metadata": metadata,
    }


def _gnp_deflator(frame: pd.DataFrame, formation_at: pd.Timestamp) -> float:
    dated = frame.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated.loc[dated["date"].le(formation_at)].dropna(subset=["gnpdef"])
    if dated.empty:
        raise RuntimeError("No causal GNP deflator is available")
    return float(dated.sort_values("date").iloc[-1]["gnpdef"])


def _security_id(row: pd.Series) -> str:
    cik = int(row["cik"])
    return f"US-SEC-{cik:010d}-{str(row['symbol']).upper()}"


def _normalize_signal_results(
    results: Iterable[pd.DataFrame],
    master: pd.DataFrame,
    registry: dict[str, SignalSpec],
    formation_at: pd.Timestamp,
    retrieved_at: str,
) -> pd.DataFrame:
    available = [frame.copy() for frame in results if frame is not None and not frame.empty]
    observed = pd.concat(available, ignore_index=True) if available else pd.DataFrame()
    if not observed.empty:
        observed["_fidelity_rank"] = observed["fidelity_class"].map(FIDELITY_ORDER).fillna(99)
        observed["_has_value"] = pd.to_numeric(observed["value"], errors="coerce").notna()
        observed = (
            observed.sort_values(
                ["symbol", "signal", "_has_value", "_fidelity_rank"],
                ascending=[True, True, False, True],
            )
            .drop_duplicates(["symbol", "signal"], keep="first")
            .drop(columns=["_fidelity_rank", "_has_value"])
        )

    identity = master[["symbol", "cik"]].drop_duplicates("symbol").copy()
    identity["security_id"] = identity.apply(_security_id, axis=1)
    grid = pd.MultiIndex.from_product(
        [identity["symbol"].astype(str), REQUIRED_93],
        names=["symbol", "signal"],
    ).to_frame(index=False)
    grid = grid.merge(identity, on="symbol", how="left", validate="many_to_one")
    frame = grid.merge(observed, on=["symbol", "signal"], how="left", validate="one_to_one")
    frame = frame.rename(columns={"symbol": "ticker", "source_ids": "source_id"})
    frame["formation_at"] = formation_at
    frame["retrieved_at"] = retrieved_at
    frame["fidelity_class"] = frame["fidelity_class"].fillna(FidelityClass.UNAVAILABLE.value)
    frame["current_usable"] = frame["current_usable"].fillna(False).astype(bool)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["filed_at"] = frame["available_at"]
    frame["natural_frequency"] = frame["signal"].map(
        {name: spec.natural_frequency for name, spec in registry.items()}
    )
    frame["openap_script"] = frame["signal"].map(
        {name: spec.openap_script for name, spec in registry.items()}
    )
    frame["staleness_days"] = pd.to_numeric(frame["staleness_days"], errors="coerce")
    calculated_staleness = (
        formation_at.normalize() - frame["available_at"].dt.normalize()
    ).dt.days
    frame["staleness_days"] = frame["staleness_days"].fillna(calculated_staleness)
    limits = frame["natural_frequency"].map(_staleness_limit)
    frame["is_current_for_natural_frequency"] = (
        frame["value"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation_at)
        & frame["staleness_days"].ge(0)
        & frame["staleness_days"].le(limits)
    )
    stale = frame["value"].notna() & ~frame["is_current_for_natural_frequency"]
    frame.loc[stale, "fidelity_class"] = FidelityClass.STALE_REFERENCE_ONLY.value
    frame.loc[stale, "current_usable"] = False
    frame["current_usable"] = (
        frame["current_usable"]
        & frame["is_current_for_natural_frequency"]
        & frame["fidelity_class"].isin(CURRENT_USABLE_CLASSES)
    )
    frame["source_id"] = frame["source_id"].fillna("")
    frame["source_url"] = frame["source_id"].map(
        lambda value: "|".join(
            SOURCE_URLS.get(item, "") for item in str(value).split("|") if item
        )
    )
    frame["formula_id"] = frame["formula_id"].fillna("")
    frame["observation_count"] = (
        pd.to_numeric(frame["observation_count"], errors="coerce").fillna(0).astype(int)
    )
    frame["reason_if_missing"] = frame["reason_if_missing"].fillna("")
    not_implemented = frame["signal"].map(lambda value: value not in IMPLEMENTED_SIGNALS)
    frame.loc[not_implemented & frame["reason_if_missing"].eq(""), "reason_if_missing"] = (
        "no_authorized_free_current_formula_implemented"
    )
    frame.loc[
        ~not_implemented & frame["value"].isna() & frame["reason_if_missing"].eq(""),
        "reason_if_missing",
    ] = "required_inputs_missing_for_security"
    frame["caveat"] = frame["caveat"].fillna("")
    frame["coverage_flag"] = np.select(
        [
            frame["current_usable"],
            frame["value"].notna() & frame["fidelity_class"].eq(
                FidelityClass.UNVALIDATED_PROXY.value
            ),
            frame["value"].notna() & frame["fidelity_class"].eq(
                FidelityClass.STALE_REFERENCE_ONLY.value
            ),
        ],
        ["current_usable", "research_only", "stale_reference_only"],
        default="missing",
    )
    frame = frame.rename(columns={"ticker": "ticker"})
    for column in REQUIRED_SIGNAL_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[list(REQUIRED_SIGNAL_COLUMNS)].sort_values(
        ["ticker", "signal"]
    ).reset_index(drop=True)


def build_validation_report(signals: pd.DataFrame) -> pd.DataFrame:
    """Emit a fail-closed validation row for every signal.

    Current-only reconstruction cannot satisfy the required 12-month overlap,
    so no proxy is promoted merely because a number exists.
    """

    rows: list[dict[str, Any]] = []
    for signal in REQUIRED_93:
        part = signals.loc[signals["signal"].eq(signal)]
        numeric = part.loc[part["value"].notna()]
        fidelities = sorted(
            set(numeric["fidelity_class"].astype(str)),
            key=lambda value: FIDELITY_ORDER.get(value, 99),
        )
        best = fidelities[0] if fidelities else FidelityClass.UNAVAILABLE.value
        if best in {FidelityClass.EXACT.value, FidelityClass.RECONSTRUCTED.value}:
            status = "formula_reconstruction_no_historical_overlap_reference"
        elif best == FidelityClass.UNVALIDATED_PROXY.value:
            status = "unvalidated_proxy_no_qualifying_overlap"
        else:
            status = "not_available_for_validation"
        rows.append(
            {
                "signal": signal,
                "fidelity_class_before_validation": best,
                "validation_status": status,
                "validation_start": "",
                "validation_end": "",
                "paired_observations": 0,
                "months": 0,
                "coverage": np.nan,
                "pearson": np.nan,
                "spearman": np.nan,
                "median_monthly_spearman": np.nan,
                "standardized_mae": np.nan,
                "sign_consistency": np.nan,
                "quintile_agreement": np.nan,
                "extreme_decile_agreement": np.nan,
                "top_bottom_overlap": np.nan,
                "next_return_ic": np.nan,
                "validated_proxy_threshold_pass": False,
                "reconstructed_target_pass": False,
                "reason": (
                    "No public point-in-time historical firm-level overlap was "
                    "available in this execution; stale OpenAP values were not "
                    "used as current data or as evidence of proxy validity."
                ),
            }
        )
    return pd.DataFrame(rows)


def _best_fidelity(part: pd.DataFrame) -> str:
    candidates = part.loc[part["value"].notna(), "fidelity_class"].astype(str).unique()
    if not len(candidates):
        return FidelityClass.UNAVAILABLE.value
    return min(candidates, key=lambda value: FIDELITY_ORDER.get(value, 99))


def build_coverage_report(
    signals: pd.DataFrame,
    registry: dict[str, SignalSpec],
    validation: pd.DataFrame,
) -> pd.DataFrame:
    validation_by_signal = validation.set_index("signal")
    rows: list[dict[str, Any]] = []
    for signal in REQUIRED_93:
        part = signals.loc[signals["signal"].eq(signal)]
        spec = registry[signal]
        sources = sorted(
            {item for value in part["source_id"] for item in str(value).split("|") if item}
        )
        best = _best_fidelity(part)
        non_null = int(part["value"].notna().sum())
        usable = int(part["current_usable"].sum())
        validation_row = validation_by_signal.loc[signal]
        rows.append(
            {
                "signal": signal,
                "status": "current_usable" if usable else (
                    "research_only" if non_null else "unavailable"
                ),
                "fidelity_class": best,
                "current_usable": bool(usable),
                "exact_formula": best in {
                    FidelityClass.EXACT.value,
                    FidelityClass.RECONSTRUCTED.value,
                },
                "primary_source": sources[0] if sources else "",
                "fallback_source": "|".join(sources[1:]),
                "source_domains": "|".join(
                    sorted({SOURCE_DOMAINS.get(item, "") for item in sources if item})
                ),
                "latest_period_end": part["period_end"].max(),
                "latest_available_at": part["available_at"].max(),
                "natural_frequency": spec.natural_frequency,
                "universe_count": len(part),
                "non_null_count": non_null,
                "current_usable_count": usable,
                "coverage_pct": 100.0 * usable / len(part) if len(part) else 0.0,
                "validation_start": validation_row["validation_start"],
                "validation_end": validation_row["validation_end"],
                "paired_observations": validation_row["paired_observations"],
                "spearman": validation_row["spearman"],
                "extreme_decile_agreement": validation_row[
                    "extreme_decile_agreement"
                ],
                "license": "|".join(
                    sorted({SOURCE_LICENSES.get(item, "") for item in sources if item})
                ),
                "terms_status": "|".join(
                    sorted({SOURCE_TERMS.get(item, "") for item in sources if item})
                ),
                "scraping_required": any(
                    source.scraping_required
                    for source in PUBLIC_SOURCES
                    if source.source_id in sources
                ),
                "reason_if_missing": "|".join(
                    sorted(set(part.loc[part["value"].isna(), "reason_if_missing"]) - {""})
                ),
                "openap_script": spec.openap_script,
                "implementation_file": _implementation_file(signal),
            }
        )
    return pd.DataFrame(rows).sort_values("signal").reset_index(drop=True)


def _implementation_file(signal: str) -> str:
    if signal in ACCOUNTING_IMPLEMENTED_SIGNALS:
        return "research/openap_93/accounting_pipeline.py"
    if signal in ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS:
        return "research/openap_93/advanced_accounting_pipeline.py"
    if signal in EVENT_IMPLEMENTED_SIGNALS:
        return "research/openap_93/event_pipeline.py"
    if signal in MARKET_IMPLEMENTED_SIGNALS:
        return "research/openap_93/market_pipeline.py"
    if signal in QUARTERLY_IMPLEMENTED_SIGNALS:
        return "research/openap_93/quarterly_pipeline.py"
    return ""


def _metadata_weights(metadata: pd.DataFrame) -> dict[tuple[str, str], float]:
    rows: dict[tuple[str, str], float] = {}
    for item in metadata.drop_duplicates("signalname").to_dict(orient="records"):
        signal = str(item["signalname"])
        rows[(signal, "exact")] = evidence_weight(item, "exact")
        rows[(signal, "proxy")] = evidence_weight(item, "proxy")
    return rows


def _integrate_features(
    base_features: pd.DataFrame,
    metadata: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    features = base_features.copy()
    base_fidelity = np.select(
        [
            features["implementation_status"].eq("exact"),
            features["implementation_status"].eq("proxy"),
        ],
        [FidelityClass.EXACT.value, FidelityClass.UNVALIDATED_PROXY.value],
        default=FidelityClass.UNAVAILABLE.value,
    )
    features["fidelity_class"] = base_fidelity
    features["is_current_for_natural_frequency"] = features["raw_value"].notna()
    updates = signals.rename(columns={"ticker": "symbol", "signal": "signalname"})
    updates = updates.set_index(["symbol", "signalname"])
    features = features.set_index(["symbol", "signalname"])
    common = features.index.intersection(updates.index)
    for target, source in (
        ("raw_value", "value"),
        ("fidelity_class", "fidelity_class"),
        ("source", "source_id"),
        ("formula_id", "formula_id"),
        ("note", "caveat"),
        ("source_available_at", "available_at"),
        ("source_input_age_days", "staleness_days"),
        ("is_current_for_natural_frequency", "is_current_for_natural_frequency"),
    ):
        features.loc[common, target] = updates.loc[common, source].to_numpy()
    features = features.reset_index()
    weights = _metadata_weights(metadata)
    implementation_class = (
        signals.loc[signals["signal"].isin(IMPLEMENTED_SIGNALS)]
        .assign(_rank=lambda frame: frame["fidelity_class"].map(FIDELITY_ORDER).fillna(99))
        .sort_values(["signal", "_rank"])
        .drop_duplicates("signal")
        .set_index("signal")["fidelity_class"]
        .to_dict()
    )
    features["formula_fidelity_class"] = features["fidelity_class"]
    mask_93 = features["signalname"].isin(REQUIRED_93)
    features.loc[mask_93, "formula_fidelity_class"] = features.loc[
        mask_93, "signalname"
    ].map(implementation_class).fillna(FidelityClass.UNAVAILABLE.value)
    features["_exact_weight"] = features["signalname"].map(
        lambda value: weights.get((str(value), "exact"), 0.0)
    )
    features["_proxy_weight"] = features["signalname"].map(
        lambda value: weights.get((str(value), "proxy"), 0.0)
    )
    return features


def _score_variant(features: pd.DataFrame, score_name: str, allowed: set[str]) -> pd.DataFrame:
    frame = features.copy()
    formula_allowed = frame["formula_fidelity_class"].isin(allowed)
    numeric_allowed = (
        frame["fidelity_class"].isin(allowed)
        & frame["raw_value"].notna()
        & frame["is_current_for_natural_frequency"].fillna(False)
    )
    proxy_formula = frame["formula_fidelity_class"].isin(
        {FidelityClass.VALIDATED_PROXY.value, FidelityClass.UNVALIDATED_PROXY.value}
    )
    frame["implementation_status"] = np.where(
        formula_allowed, np.where(proxy_formula, "proxy", "exact"), "unavailable"
    )
    frame["status"] = np.where(
        numeric_allowed, np.where(proxy_formula, "proxy", "exact"), "unavailable"
    )
    frame["value_status"] = np.where(numeric_allowed, "computed", "missing_or_excluded")
    potential = np.where(proxy_formula, frame["_proxy_weight"], frame["_exact_weight"])
    frame["potential_evidence_weight"] = np.where(formula_allowed, potential, 0.0)
    frame["evidence_weight"] = np.where(numeric_allowed, potential, 0.0)
    frame["percentile"] = np.nan
    frame["score_percentile"] = np.nan
    for signal, index in frame.groupby("signalname").groups.items():
        group_index = pd.Index(index)
        valid = numeric_allowed.loc[group_index]
        if not valid.any():
            continue
        sign = pd.to_numeric(frame.loc[group_index, "sign"], errors="coerce").dropna()
        direction = float(sign.iloc[0]) if not sign.empty else 1.0
        percentile = signed_percentile(
            frame.loc[group_index, "raw_value"].where(valid), direction
        )
        frame.loc[group_index, "percentile"] = percentile
        frame.loc[group_index, "score_percentile"] = percentile
    overall = frame.copy()
    overall["horizon_months"] = 0
    scores = calculate_scores(overall, minimum_metrics=5)
    scores = scores.loc[scores["horizon_months"].eq(0)].copy()
    keep = [
        "symbol",
        "score",
        "confidence",
        "metrics_used",
        "metrics_expected",
        "groups_used",
        "groups_expected",
    ]
    scores = scores[keep].rename(
        columns={
            "score": score_name,
            "confidence": f"{score_name}_confidence",
            "metrics_used": f"{score_name}_metrics_used",
            "metrics_expected": f"{score_name}_metrics_expected",
            "groups_used": f"{score_name}_groups_used",
            "groups_expected": f"{score_name}_groups_expected",
        }
    )
    expected = pd.to_numeric(scores[f"{score_name}_metrics_expected"], errors="coerce")
    used = pd.to_numeric(scores[f"{score_name}_metrics_used"], errors="coerce")
    scores[f"{score_name}_coverage_pct"] = 100.0 * used / expected.replace(0, np.nan)
    scores[f"{score_name}_ranking_eligible"] = scores[
        f"{score_name}_coverage_pct"
    ].ge(70.0)
    return scores


def build_score_table(
    base_features: pd.DataFrame,
    metadata: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    integrated = _integrate_features(base_features, metadata, signals)
    symbols = pd.DataFrame({"symbol": sorted(set(integrated["symbol"].astype(str)))})
    score_table = symbols
    for score_name, allowed in SCORE_VARIANTS.items():
        score_table = score_table.merge(
            _score_variant(integrated, score_name, set(allowed)),
            on="symbol",
            how="left",
            validate="one_to_one",
        )
    counts = integrated.copy()
    numeric_current = (
        counts["raw_value"].notna()
        & counts["is_current_for_natural_frequency"].fillna(False)
        & counts["fidelity_class"].ne(FidelityClass.STALE_REFERENCE_ONLY.value)
    )
    counts["_numeric"] = numeric_current.astype(int)
    for fidelity in FidelityClass:
        counts[f"_{fidelity.value}"] = (
            numeric_current & counts["fidelity_class"].eq(fidelity.value)
        ).astype(int)
    counts["_previous"] = (numeric_current & ~counts["signalname"].isin(REQUIRED_93)).astype(int)
    counts["_new"] = (numeric_current & counts["signalname"].isin(REQUIRED_93)).astype(int)
    summary = counts.groupby("symbol", as_index=False).agg(
        signals_total=("_numeric", "sum"),
        signals_previous_92=("_previous", "sum"),
        signals_new_93=("_new", "sum"),
        exact_count=("_exact", "sum"),
        reconstructed_count=("_reconstructed", "sum"),
        validated_proxy_count=("_validated_proxy", "sum"),
        unvalidated_proxy_count=("_unvalidated_proxy", "sum"),
        stale_reference_count=("_stale_reference_only", "sum"),
    )
    summary["missing_count"] = 185 - summary["signals_total"]
    summary["coverage_pct"] = 100.0 * summary["signals_total"] / 185.0
    oldest = (
        signals.loc[signals["value"].notna()]
        .groupby("ticker", as_index=False)["available_at"]
        .min()
        .rename(columns={"ticker": "symbol", "available_at": "oldest_new_input_available_at"})
    )
    score_table = score_table.merge(summary, on="symbol", how="left", validate="one_to_one")
    score_table = score_table.merge(oldest, on="symbol", how="left", validate="one_to_one")
    score_table["quality_flags"] = np.where(
        score_table["coverage_pct"].ge(70.0), "", "below_70pct_total_coverage"
    )
    return score_table.sort_values(
        ["score_max_current", "score_strict_current"], ascending=[False, False]
    ).reset_index(drop=True)


def _copy_report(source: Path, target: Path) -> None:
    if not source.exists():
        raise RuntimeError(f"Required source report does not exist: {source}")
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)


def _write_final_report(
    path: Path,
    coverage: pd.DataFrame,
    selected_sources: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    exact = int(coverage["fidelity_class"].eq(FidelityClass.EXACT.value).sum())
    reconstructed = int(
        coverage["fidelity_class"].eq(FidelityClass.RECONSTRUCTED.value).sum()
    )
    validated = int(
        coverage["fidelity_class"].eq(FidelityClass.VALIDATED_PROXY.value).sum()
    )
    unvalidated = int(
        coverage["fidelity_class"].eq(FidelityClass.UNVALIDATED_PROXY.value).sum()
    )
    unavailable = 93 - exact - reconstructed - validated - unvalidated
    selected = selected_sources.get("selected_source_ids", [])
    table_columns = ["signal", "fidelity_class", "current_usable_count", "coverage_pct"]
    table = coverage[table_columns].copy()
    header = "| " + " | ".join(table_columns) + " |"
    divider = "| " + " | ".join("---" for _ in table_columns) + " |"
    table_rows = [header, divider]
    for row in table.itertuples(index=False, name=None):
        table_rows.append("| " + " | ".join(str(value) for value in row) + " |")
    lines = [
        "# OpenAP 93 Current Maximum-Free Report",
        "",
        "## RESULTADO",
        "",
        f"- Exactas actuales: {exact}",
        f"- Reconstruidas actuales: {reconstructed}",
        f"- Proxies validados actuales: {validated}",
        f"- Total actual utilizable: {exact + reconstructed + validated} de 93",
        f"- Proxies no validados: {unvalidated}",
        f"- No disponibles: {unavailable}",
        f"- Numero de dominios en la combinacion seleccionada: {len(selected_sources.get('selected_domains', []))}",
        "",
        "## Combinacion Seleccionada",
        "",
        ", ".join(selected) if selected else "Ninguna fuente supero el contrato completo.",
        "",
        "## Limites Reales",
        "",
        "- Los proxies sin solapamiento historico suficiente permanecen fuera del score principal.",
        "- Los valores antiguos de OpenAP se usan solo como referencia, nunca como observacion actual.",
        "- Las senales no soportadas se conservan como filas unavailable con motivo explicito.",
        "",
        "## Reejecucion",
        "",
        "Use `python scripts/run_openap_93_max_free.py run --help` dentro de GitHub Actions.",
        "",
        "## Ejecucion",
        "",
        f"- Formation date: {manifest['formation_at']}",
        f"- Retrieved at: {manifest['retrieved_at']}",
        f"- Runtime seconds: {manifest['runtime_seconds']}",
        f"- OpenAP commit: {manifest['openap_commit']}",
        f"- Base database SHA-256: {manifest['base_database_sha256']}",
        "",
        "## Cobertura Por Senal",
        "",
        *table_rows,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_current_pipeline(
    *,
    base_database: str | Path,
    normalized_public_inputs: str | Path,
    source_probe_dir: str | Path,
    output_dir: str | Path,
    registry: dict[str, SignalSpec],
    formation_at: str | pd.Timestamp,
    universe_symbols: set[str] | None = None,
    selected_signals: set[str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    formation = pd.Timestamp(formation_at).tz_localize(None)
    retrieved_at = _utcnow()
    database = _find_database(base_database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    public = _load_public_frames(normalized_public_inputs)
    base = _load_base_frames(database, formation, universe_symbols)

    results = [
        calculate_market_signals(
            base["master"],
            base["prices"],
            public["ff3_daily"],
            public["ff3_monthly"],
            public["liquidity_monthly"],
            public["vix_daily"],
            formation_at=formation,
        ),
        calculate_accounting_signals(
            base["master"],
            base["concepts"],
            formation_at=formation,
            gnp_deflator=_gnp_deflator(public["gnp_deflator"], formation),
        ),
        calculate_advanced_accounting_signals(
            base["master"],
            base["companyfacts"],
            base["submissions"],
            base["prices"],
            public["gnp_deflator"],
            formation_at=formation,
        ),
        calculate_quarterly_signals(
            base["master"],
            base["companyfacts"],
            base["prices"],
            public["ff3_daily"],
            formation_at=formation,
        ),
        calculate_event_signals(
            base["master"], base["prices"], formation_at=formation
        ),
    ]
    signals = _normalize_signal_results(
        results, base["master"], registry, formation, retrieved_at
    )
    if selected_signals is not None:
        unknown = selected_signals - set(REQUIRED_93)
        if unknown:
            raise RuntimeError(f"Unknown requested signals: {sorted(unknown)}")
        signals = signals.loc[signals["signal"].isin(selected_signals)].copy()
    if selected_signals is None and signals["signal"].nunique() != 93:
        raise RuntimeError("The final current-signal table does not contain all 93 signals")
    if signals["security_id"].isna().any() or signals["ticker"].isna().any():
        raise RuntimeError("Final current-signal table contains null identifiers")
    causal = signals["available_at"].isna() | signals["available_at"].le(formation)
    if not causal.all():
        raise RuntimeError("Point-in-time violation: available_at is after formation_at")
    finite = signals["value"].dropna().map(np.isfinite)
    if not finite.all():
        raise RuntimeError("Non-finite values reached the final current-signal table")

    validation = build_validation_report(signals)
    coverage = build_coverage_report(signals, registry, validation)
    score_table = build_score_table(base["features"], base["metadata"], signals)

    signals.to_parquet(output / "signals_93_current.parquet", index=False, compression="zstd")
    signals.to_csv(output / "signals_93_current.csv", index=False)
    score_table.to_parquet(output / "score_185_current.parquet", index=False, compression="zstd")
    score_table.to_csv(output / "score_185_current.csv", index=False)
    coverage.to_csv(output / "coverage_93.csv", index=False)
    validation.to_csv(output / "validation_per_signal.csv", index=False)
    pd.DataFrame(columns=["signal", "month", "paired_observations", "spearman"]).to_parquet(
        output / "validation_per_month.parquet", index=False, compression="zstd"
    )
    (output / "validation_summary.md").write_text(
        "# Validation Summary\n\nNo proxy met the historical-overlap contract; no proxy was promoted.\n",
        encoding="utf-8",
    )

    probe = Path(source_probe_dir)
    for name in (
        "source_coverage_matrix.csv",
        "source_ablation.csv",
        "selected_sources.json",
        "sources.lock.json",
    ):
        _copy_report(probe / name, output / name)
    selected_sources = json.loads((output / "selected_sources.json").read_text(encoding="utf-8"))

    runtime_seconds = round(time.monotonic() - started, 3)
    manifest = {
        "formation_at": formation.isoformat(),
        "retrieved_at": retrieved_at,
        "runtime_seconds": runtime_seconds,
        "input_signals": 93,
        "universe_count": int(signals["ticker"].nunique()),
        "rows": int(len(signals)),
        "base_database": str(database),
        "base_database_sha256": _sha256(database),
        "openap_commit": "8db892442c2c3a3779b0f1eac4370d3655be15a1",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "api_keys_required": False,
        "manual_actions_required": False,
        "selected_signals": sorted(selected_signals) if selected_signals else list(REQUIRED_93),
    }
    hashes: dict[str, str] = {}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name not in {"run_manifest.json", "FINAL_REPORT.md"}:
            hashes[path.name] = _sha256(path)
    manifest["output_hashes"] = hashes
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    lineage = {
        "base_database": {
            "path": str(database),
            "sha256": manifest["base_database_sha256"],
        },
        "public_inputs": json.loads(
            (Path(normalized_public_inputs).parent / "public_inputs_manifest.json").read_text(
                encoding="utf-8"
            )
        ),
        "signal_formulas": {
            name: {
                "openap_script": spec.openap_script,
                "required_inputs": list(spec.required_inputs),
                "candidate_sources": list(spec.candidate_sources),
            }
            for name, spec in registry.items()
        },
        "generated_at": retrieved_at,
    }
    (output / "data_lineage.json").write_text(
        json.dumps(lineage, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    failures = {
        "signals": coverage.loc[~coverage["current_usable"]][
            ["signal", "fidelity_class", "reason_if_missing"]
        ].to_dict(orient="records"),
        "critical_failures": [],
        "generated_at": retrieved_at,
    }
    (output / "failures.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    _write_final_report(output / "FINAL_REPORT.md", coverage, selected_sources, manifest)
    return manifest


__all__ = [
    "IMPLEMENTED_SIGNALS",
    "REQUIRED_SIGNAL_COLUMNS",
    "SCORE_VARIANTS",
    "build_coverage_report",
    "build_score_table",
    "build_validation_report",
    "run_current_pipeline",
]
