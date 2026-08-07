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
    ANNUAL_ALIASES,
    calculate_advanced_accounting_signals,
)
from .analyst_pipeline import (
    ANALYST_IMPLEMENTED_SIGNALS,
    EPS_FACT_TAGS,
    calculate_analyst_signals,
)
from .earnings_events import build_earnings_events
from .event_pipeline import EVENT_IMPLEMENTED_SIGNALS, calculate_event_signals
from .forward_proxy_validation import (
    ForwardProxyCertificate,
    apply_certificates,
    certificate_sha256,
    formula_identity_sha256,
    formula_hashes_from_source_manifest,
)
from .institutional_pipeline import (
    INSTITUTIONAL_IMPLEMENTED_SIGNALS,
    calculate_institutional_signals,
)
from .market_pipeline import MARKET_IMPLEMENTED_SIGNALS, calculate_market_signals
from .quarterly_pipeline import (
    ASSET_TAGS,
    NET_INCOME_TAGS,
    QUARTERLY_IMPLEMENTED_SIGNALS,
    REVENUE_TAGS,
    SHARE_TAGS,
    calculate_quarterly_signals,
)
from .short_interest_pipeline import (
    SHORT_INTEREST_IMPLEMENTED_SIGNALS,
    calculate_short_interest_signals,
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
    "variant_id",
    "formula_id",
    "openap_script",
    "natural_frequency",
    "staleness_days",
    "is_current_for_natural_frequency",
    "observation_count",
    "reason_if_missing",
    "caveat",
    "formula_sha256",
    "source_manifest_sha256",
    "certificate_status",
    "certificate_sha256",
    "effective_score_weight",
    "forward_advisory_usable",
    "forward_advisory_status",
    "forward_advisory_score_weight",
    "forward_historical_pearson",
    "forward_historical_spearman",
    "forward_historical_sign_agreement",
    "forward_historical_common_months",
    "forward_selected_variant",
    "forward_advisory_reason",
)

FIVE_FORWARD_PROXY_SIGNALS = frozenset(
    {
        "DivSeason",
        "AnnouncementReturn",
        "EarningsStreak",
        "IndRetBig",
        "DelNetFin",
    }
)

IMPLEMENTED_SIGNALS = frozenset(
    ACCOUNTING_IMPLEMENTED_SIGNALS
    | ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS
    | ANALYST_IMPLEMENTED_SIGNALS
    | EVENT_IMPLEMENTED_SIGNALS
    | INSTITUTIONAL_IMPLEMENTED_SIGNALS
    | MARKET_IMPLEMENTED_SIGNALS
    | QUARTERLY_IMPLEMENTED_SIGNALS
    | SHORT_INTEREST_IMPLEMENTED_SIGNALS
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

# The longest implemented price formula needs 60 monthly lags.  Keeping seven
# years gives those formulas a generous buffer without materialising the entire
# 18M-row price history in pandas on a standard GitHub runner.
PRICE_LOOKBACK_MONTHS = 84
COMPANYFACT_TAGS = frozenset(
    tag
    for aliases in ANNUAL_ALIASES.values()
    for tag in aliases
) | frozenset(
    NET_INCOME_TAGS + REVENUE_TAGS + SHARE_TAGS + ASSET_TAGS + EPS_FACT_TAGS
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_forward_proxy_certificates(
    path: str | Path | None,
) -> list[ForwardProxyCertificate]:
    if path is None or not str(path).strip():
        return []
    source = Path(path)
    if not source.is_file():
        raise RuntimeError(f"Forward-proxy certificate file does not exist: {source}")
    certificates: list[ForwardProxyCertificate] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        recorded_hash = payload.pop("certificate_sha256", None)
        certificate = ForwardProxyCertificate(**payload)
        actual_hash = certificate_sha256(certificate)
        if recorded_hash is not None and str(recorded_hash) != actual_hash:
            raise RuntimeError(
                f"Forward-proxy certificate hash mismatch on line {line_number}"
            )
        certificates.append(certificate)
    return certificates


def apply_forward_proxy_certificates_to_signals(
    signals: pd.DataFrame,
    certificates: Iterable[ForwardProxyCertificate],
    *,
    source_manifest_sha256: str,
    formula_hashes: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fail closed for the five forward proxies while leaving other signals unchanged."""

    result = signals.copy()
    for required in ("signal", "formula_id", "current_usable"):
        if required not in result.columns:
            raise ValueError(f"signals column missing: {required}")
    if "variant_id" not in result.columns:
        result["variant_id"] = result["formula_id"]
    result["variant_id"] = result["variant_id"].fillna("").astype(str)
    result["formula_id"] = result["formula_id"].fillna("").astype(str)
    blank_variant = result["variant_id"].str.strip().eq("")
    result.loc[blank_variant, "variant_id"] = result.loc[blank_variant, "formula_id"]
    known_formula_hashes = formula_hashes or {}
    result["formula_sha256"] = result.apply(
        lambda row: known_formula_hashes.get(
            str(row["signal"]),
            formula_identity_sha256(row["formula_id"])
            if str(row["formula_id"]).strip()
            else "",
        ),
        axis=1,
    )
    result["source_manifest_sha256"] = str(source_manifest_sha256)
    result["certificate_status"] = "not_required"
    result["certificate_sha256"] = None
    result["effective_score_weight"] = np.where(
        result["current_usable"].fillna(False).astype(bool), 1.0, 0.0
    )
    result["forward_advisory_usable"] = result["current_usable"].fillna(False).astype(bool)
    result["forward_advisory_status"] = "not_required"
    result["forward_advisory_score_weight"] = result["effective_score_weight"]
    result["forward_historical_pearson"] = np.nan
    result["forward_historical_spearman"] = np.nan
    result["forward_historical_sign_agreement"] = np.nan
    result["forward_historical_common_months"] = 0
    result["forward_selected_variant"] = ""
    result["forward_advisory_reason"] = "not_a_forward_proxy_signal"

    protected = result["signal"].isin(FIVE_FORWARD_PROXY_SIGNALS)
    if not protected.any():
        return result
    protected_rows = result.loc[protected].copy()
    protected_rows["base_score_weight"] = 1.0
    protected_rows = apply_certificates(protected_rows, certificates)
    for column in (
        "variant_id",
        "formula_sha256",
        "source_manifest_sha256",
        "certificate_status",
        "certificate_sha256",
        "current_usable",
        "effective_score_weight",
        "forward_advisory_usable",
        "forward_advisory_status",
        "forward_advisory_score_weight",
        "forward_historical_pearson",
        "forward_historical_spearman",
        "forward_historical_sign_agreement",
        "forward_historical_common_months",
        "forward_selected_variant",
        "forward_advisory_reason",
    ):
        result.loc[protected, column] = protected_rows[column].to_numpy()
    return result


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
        "ff48_sic_codes",
        "liquidity_monthly",
        "vix_daily",
        "gnp_deflator",
        "signal_doc",
        "openap_reference_sample",
        "sec_13f_filings",
        "sec_13f_holdings",
        "sec_13f_exclusions",
        "openfigi_cusip_map",
    )
    frames: dict[str, pd.DataFrame] = {}
    for name in required:
        path = root / f"{name}.parquet"
        if not path.exists():
            raise RuntimeError(f"Missing normalized public input: {path}")
        frames[name] = pd.read_parquet(path)
        if frames[name].empty and name != "sec_13f_exclusions":
            raise RuntimeError(f"Normalized public input is empty: {name}")
    return frames


def _load_base_frames(
    database: Path,
    formation_at: pd.Timestamp,
    universe_symbols: set[str] | None,
) -> dict[str, Any]:
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
        connection.register(
            "required_companyfact_tags",
            pd.DataFrame({"tag": sorted(COMPANYFACT_TAGS)}),
        )
        price_start = formation_at - pd.DateOffset(months=PRICE_LOOKBACK_MONTHS)
        prices = connection.execute(
            """
            SELECT p.date, p.symbol, p.open, p.high, p.low, p.close,
                   p.adj_close, p.volume, p.dividends, p.stock_splits,
                   p.source, p.retrieved_at
            FROM prices_daily_clean p
            INNER JOIN selected_symbols s USING (symbol)
            WHERE p.date BETWEEN ? AND ?
            ORDER BY p.symbol, p.date
            """,
            [price_start, formation_at],
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
            SELECT f.cik, m.symbol, f.entity_name, f.taxonomy, f.tag, f.unit,
                   f.value, f.period_start, f.period_end, f.fy, f.fp, f.form,
                   f.filed, f.accession_number, f.frame, f.available_at,
                   f.available_at_quality, f.source, f.source_mode
            FROM sec_companyfacts f
            INNER JOIN security_master m USING (cik)
            INNER JOIN selected_symbols s ON s.symbol = m.symbol
            INNER JOIN required_companyfact_tags t ON t.tag = f.tag
            WHERE f.available_at <= ?
            """,
            [formation_at],
        ).fetchdf()
        submission_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info('sec_submissions')").fetchall()
        }
        items_expression = "u.items" if "items" in submission_columns else "NULL AS items"
        submissions = connection.execute(
            f"""
            SELECT u.cik, u.accession_number, u.filing_date, u.accepted_at,
                   u.report_date, u.form, {items_expression}, u.sic, u.sic_description,
                   u.source, u.source_mode
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
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        if "yahoo_analyst_current" in table_names:
            analyst = connection.execute(
                """
                SELECT a.symbol, a.dataset, a.retrieved_at, a.payload_json
                FROM yahoo_analyst_current a
                INNER JOIN selected_symbols s USING (symbol)
                WHERE TRY_CAST(a.retrieved_at AS TIMESTAMPTZ) <= ?
                """,
                [formation_at],
            ).fetchdf()
        else:
            analyst = pd.DataFrame(
                columns=["symbol", "dataset", "retrieved_at", "payload_json"]
            )
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
        "analyst": analyst,
        "load_audit": {
            "price_lookback_months": PRICE_LOOKBACK_MONTHS,
            "price_start": price_start.isoformat(),
            "companyfact_tags_requested": len(COMPANYFACT_TAGS),
            "master_rows": int(len(master)),
            "price_rows": int(len(prices)),
            "concept_rows": int(len(concepts)),
            "companyfact_rows": int(len(companyfacts)),
            "submission_rows": int(len(submissions)),
            "base_feature_rows": int(len(features)),
            "metadata_rows": int(len(metadata)),
            "analyst_rows": int(len(analyst)),
        },
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
    frame["variant_id"] = frame["variant_id"].fillna("").astype(str)
    blank_variant = frame["variant_id"].str.strip().eq("")
    frame.loc[blank_variant, "variant_id"] = frame.loc[blank_variant, "formula_id"]
    frame["observation_count"] = (
        pd.to_numeric(frame["observation_count"], errors="coerce").fillna(0).astype(int)
    )
    frame["reason_if_missing"] = frame["reason_if_missing"].fillna("")
    not_implemented = frame["signal"].map(lambda value: value not in IMPLEMENTED_SIGNALS)
    registry_reasons = frame["signal"].map(
        {name: spec.notes for name, spec in registry.items()}
    ).fillna("")
    frame.loc[not_implemented & frame["reason_if_missing"].eq(""), "reason_if_missing"] = (
        registry_reasons.loc[not_implemented & frame["reason_if_missing"].eq("")]
    )
    frame.loc[not_implemented & frame["reason_if_missing"].eq(""), "reason_if_missing"] = (
        "no_authorized_free_current_formula_implemented_and_no_specific_blocker_recorded"
    )
    frame.loc[
        ~not_implemented & frame["value"].isna() & frame["reason_if_missing"].eq(""),
        "reason_if_missing",
    ] = "required_inputs_missing_for_security"
    frame["caveat"] = frame["caveat"].fillna("")
    not_applicable = (
        frame["value"].isna()
        & frame["reason_if_missing"].str.startswith("not_applicable:")
    )
    frame["coverage_flag"] = np.select(
        [
            frame["current_usable"],
            frame["value"].notna() & frame["fidelity_class"].eq(
                FidelityClass.UNVALIDATED_PROXY.value
            ),
            frame["value"].notna() & frame["fidelity_class"].eq(
                FidelityClass.STALE_REFERENCE_ONLY.value
            ),
            not_applicable,
        ],
        [
            "current_usable",
            "research_only",
            "stale_reference_only",
            "not_applicable",
        ],
        default="missing",
    )
    frame = frame.rename(columns={"ticker": "ticker"})
    for column in REQUIRED_SIGNAL_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[list(REQUIRED_SIGNAL_COLUMNS)].sort_values(
        ["ticker", "signal"]
    ).reset_index(drop=True)


def build_validation_report(
    signals: pd.DataFrame,
    openap_reference_sample: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Emit a fail-closed validation row for every signal.

    Current-only reconstruction cannot satisfy the required 12-month overlap,
    so no proxy is promoted merely because a number exists.
    """

    reference = (
        openap_reference_sample
        if openap_reference_sample is not None
        else pd.DataFrame()
    )
    reference_has_permno = {"permno", "yyyymm"} <= set(reference.columns)
    reference_has_public_identity = bool(
        {"ticker", "cik", "security_id"} & set(reference.columns)
    )
    identity_crosswalk_available = reference_has_permno and reference_has_public_identity
    if reference_has_permno and not identity_crosswalk_available:
        reference_reason = (
            "The latest official OpenAP firm-level reference was downloaded "
            "and inspected, but it exposes permno and yyyymm only. The current "
            "Aurora universe uses CIK and ticker, and no free authorized "
            "point-in-time permno crosswalk is available. Therefore no proxy "
            "is promoted from unpaired or stale observations."
        )
    else:
        reference_reason = (
            "No public point-in-time historical firm-level overlap was "
            "available in this execution; stale OpenAP values were not "
            "used as current data or as evidence of proxy validity."
        )
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
                "reference_rows_inspected": int(len(reference)),
                "reference_identifier": "permno|yyyymm" if reference_has_permno else "",
                "identity_crosswalk_available": identity_crosswalk_available,
                "reason": reference_reason,
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
        not_applicable = int(part["coverage_flag"].eq("not_applicable").sum())
        applicable = max(0, len(part) - not_applicable)
        validation_row = validation_by_signal.loc[signal]
        rows.append(
            {
                "signal": signal,
                "status": (
                    "current_usable"
                    if usable
                    else "research_only"
                    if non_null
                    else "not_applicable"
                    if not_applicable == len(part)
                    else "unavailable"
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
                "applicable_count": applicable,
                "non_null_count": non_null,
                "current_usable_count": usable,
                "not_applicable_count": not_applicable,
                "missing_count": max(0, len(part) - non_null - not_applicable),
                "coverage_pct": 100.0 * usable / applicable if applicable else 0.0,
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
                "registry_notes": spec.notes,
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
    if signal in ANALYST_IMPLEMENTED_SIGNALS:
        return "research/openap_93/analyst_pipeline.py"
    if signal in EVENT_IMPLEMENTED_SIGNALS:
        return "research/openap_93/event_pipeline.py"
    if signal in INSTITUTIONAL_IMPLEMENTED_SIGNALS:
        return "research/openap_93/institutional_pipeline.py"
    if signal in MARKET_IMPLEMENTED_SIGNALS:
        return "research/openap_93/market_pipeline.py"
    if signal in QUARTERLY_IMPLEMENTED_SIGNALS:
        return "research/openap_93/quarterly_pipeline.py"
    if signal in SHORT_INTEREST_IMPLEMENTED_SIGNALS:
        return "research/openap_93/short_interest_pipeline.py"
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
    *,
    forward_proxy_mode: str = "strict",
) -> pd.DataFrame:
    if forward_proxy_mode not in {"strict", "advisory"}:
        raise ValueError("forward_proxy_mode must be 'strict' or 'advisory'")
    features = base_features.copy()
    for column in ("raw_value", "source_input_age_days"):
        features[column] = pd.to_numeric(features[column], errors="coerce").astype(float)
    features["source_available_at"] = pd.to_datetime(
        features["source_available_at"], errors="coerce", utc=True
    ).dt.tz_convert(None)
    for column in (
        "source",
        "formula_id",
        "note",
        "value_status",
    ):
        features[column] = features[column].astype(object)
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
    features["certificate_current_usable"] = True
    features["effective_score_weight"] = 1.0
    updates = signals.rename(columns={"ticker": "symbol", "signal": "signalname"})
    if "forward_advisory_usable" not in updates:
        updates["forward_advisory_usable"] = updates["current_usable"]
    if "forward_advisory_score_weight" not in updates:
        updates["forward_advisory_score_weight"] = updates["effective_score_weight"]
    updates["available_at"] = pd.to_datetime(
        updates["available_at"], errors="coerce", utc=True
    ).dt.tz_convert(None)
    updates = updates.set_index(["symbol", "signalname"])
    features = features.set_index(["symbol", "signalname"])
    common = features.index.intersection(updates.index)
    usable_column = (
        "current_usable"
        if forward_proxy_mode == "strict"
        else "forward_advisory_usable"
    )
    weight_column = (
        "effective_score_weight"
        if forward_proxy_mode == "strict"
        else "forward_advisory_score_weight"
    )
    for target, source in (
        ("raw_value", "value"),
        ("fidelity_class", "fidelity_class"),
        ("source", "source_id"),
        ("formula_id", "formula_id"),
        ("note", "caveat"),
        ("source_available_at", "available_at"),
        ("source_input_age_days", "staleness_days"),
        ("is_current_for_natural_frequency", "is_current_for_natural_frequency"),
        ("value_status", "coverage_flag"),
        ("certificate_current_usable", usable_column),
        ("effective_score_weight", weight_column),
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
    not_applicable = frame.get(
        "value_status", pd.Series("", index=frame.index, dtype=str)
    ).eq("not_applicable")
    formula_allowed = frame["formula_fidelity_class"].isin(allowed)
    numeric_allowed = (
        frame["fidelity_class"].isin(allowed)
        & frame["raw_value"].notna()
        & frame["is_current_for_natural_frequency"].fillna(False)
        & frame["certificate_current_usable"].fillna(False)
        & pd.to_numeric(frame["effective_score_weight"], errors="coerce")
        .fillna(0.0)
        .gt(0.0)
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
    frame["value_status"] = np.select(
        [numeric_allowed, not_applicable],
        ["computed", "not_applicable"],
        default="missing_or_excluded",
    )
    potential = np.where(proxy_formula, frame["_proxy_weight"], frame["_exact_weight"])
    frame["potential_evidence_weight"] = np.where(formula_allowed, potential, 0.0)
    frame["evidence_weight"] = np.where(
        numeric_allowed,
        potential
        * pd.to_numeric(frame["effective_score_weight"], errors="coerce").fillna(0.0),
        0.0,
    )
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


def _score_identity(signals: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "security_id", "cik"}
    missing = sorted(required - set(signals.columns))
    if missing:
        raise RuntimeError(f"Score identity columns are missing: {missing}")
    identity = (
        signals[["ticker", "security_id", "cik"]]
        .drop_duplicates()
        .rename(columns={"ticker": "symbol"})
        .reset_index(drop=True)
    )
    if identity["symbol"].duplicated().any():
        raise RuntimeError("A symbol maps to multiple score identities")
    if identity["security_id"].isna().any() or identity["security_id"].duplicated().any():
        raise RuntimeError("Score security_id values must be present and unique")
    return identity


def build_score_table(
    base_features: pd.DataFrame,
    metadata: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    forward_proxy_mode: str = "strict",
) -> pd.DataFrame:
    integrated = _integrate_features(
        base_features,
        metadata,
        signals,
        forward_proxy_mode=forward_proxy_mode,
    )
    score_table = _score_identity(signals)
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
    counts["_not_applicable"] = counts["value_status"].eq("not_applicable").astype(int)
    summary = counts.groupby("symbol", as_index=False).agg(
        signals_total=("_numeric", "sum"),
        signals_previous_92=("_previous", "sum"),
        signals_new_93=("_new", "sum"),
        exact_count=("_exact", "sum"),
        reconstructed_count=("_reconstructed", "sum"),
        validated_proxy_count=("_validated_proxy", "sum"),
        unvalidated_proxy_count=("_unvalidated_proxy", "sum"),
        stale_reference_count=("_stale_reference_only", "sum"),
        not_applicable_count=("_not_applicable", "sum"),
    )
    summary["applicable_count"] = 185 - summary["not_applicable_count"]
    summary["missing_count"] = (
        summary["applicable_count"] - summary["signals_total"]
    ).clip(lower=0)
    summary["coverage_pct"] = (
        100.0
        * summary["signals_total"]
        / summary["applicable_count"].replace(0, np.nan)
    )
    oldest = (
        signals.loc[signals["value"].notna()]
        .groupby("ticker", as_index=False)["available_at"]
        .min()
        .rename(columns={"ticker": "symbol", "available_at": "oldest_new_input_available_at"})
    )
    score_table = score_table.merge(summary, on="symbol", how="left", validate="one_to_one")
    score_table = score_table.merge(oldest, on="symbol", how="left", validate="one_to_one")
    score_table["forward_proxy_mode"] = forward_proxy_mode
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


def _institutional_input_audit(
    public_inputs: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    filings = public_inputs["sec_13f_filings"]
    holdings = public_inputs["sec_13f_holdings"]
    exclusions = public_inputs["sec_13f_exclusions"]
    mapping = public_inputs["openfigi_cusip_map"]
    status_counts = {
        str(status): int(count)
        for status, count in mapping["mapping_status"].value_counts(dropna=False).items()
    }
    mapped_cusips = set(
        mapping.loc[mapping["mapping_status"].eq("mapped_unique"), "cusip"].astype(str)
    )
    holding_cusips = holdings["cusip"].astype(str)
    mapped_holding_rows = int(holding_cusips.isin(mapped_cusips).sum())
    latest_report = pd.to_datetime(filings["report_period"], errors="coerce").max()
    latest_filing = pd.to_datetime(filings["filing_date"], errors="coerce").max()
    payload: dict[str, Any] = {
        "filing_rows": int(len(filings)),
        "holding_rows": int(len(holdings)),
        "excluded_amendment_groups": int(len(exclusions)),
        "cusips_requested": int(mapping["cusip"].nunique()),
        "mapping_status_counts": status_counts,
        "mapped_holding_rows": mapped_holding_rows,
        "mapped_holding_rows_pct": (
            round(100.0 * mapped_holding_rows / len(holdings), 6)
            if len(holdings)
            else 0.0
        ),
        "latest_report_period": (
            pd.Timestamp(latest_report).isoformat() if pd.notna(latest_report) else None
        ),
        "latest_filing_date": (
            pd.Timestamp(latest_filing).isoformat() if pd.notna(latest_filing) else None
        ),
        "request_failed_count": int(status_counts.get("request_failed", 0)),
        "ambiguous_count": int(status_counts.get("ambiguous", 0)),
        "no_common_stock_match_count": int(
            status_counts.get("no_common_stock_match", 0)
        ),
    }
    rows: list[dict[str, Any]] = []
    for metric, value in payload.items():
        rows.append(
            {
                "metric": metric,
                "value": json.dumps(value, sort_keys=True)
                if isinstance(value, dict)
                else value,
            }
        )
    return pd.DataFrame(rows), payload


def _write_final_report(
    path: Path,
    coverage: pd.DataFrame,
    score_table: pd.DataFrame,
    selected_sources: dict[str, Any],
    manifest: dict[str, Any],
    source_probes: pd.DataFrame,
    artifact_size_bytes: int = 0,
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
    stale_reference = int(
        coverage["fidelity_class"].eq(FidelityClass.STALE_REFERENCE_ONLY.value).sum()
    )
    unavailable = int(
        coverage["fidelity_class"].eq(FidelityClass.UNAVAILABLE.value).sum()
    )
    selected = selected_sources.get("selected_source_ids", [])
    usable_total = exact + reconstructed + validated
    mean_signal_coverage = float(
        pd.to_numeric(coverage["coverage_pct"], errors="coerce").fillna(0.0).mean()
    )
    company_coverage = pd.to_numeric(
        score_table.get("coverage_pct", pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    probe_failures = source_probes.loc[~source_probes["probe_ok"].fillna(False)]
    unavailable_names = coverage.loc[
        coverage["status"].eq("unavailable"), "signal"
    ].astype(str).tolist()
    not_applicable_names = coverage.loc[
        coverage["status"].eq("not_applicable"), "signal"
    ].astype(str).tolist()
    research_only_names = coverage.loc[
        coverage["status"].eq("research_only"), "signal"
    ].astype(str).tolist()
    table_columns = ["signal", "fidelity_class", "current_usable_count", "coverage_pct"]
    table = coverage[table_columns].copy()
    header = "| " + " | ".join(table_columns) + " |"
    divider = "| " + " | ".join("---" for _ in table_columns) + " |"
    table_rows = [header, divider]
    for row in table.itertuples(index=False, name=None):
        table_rows.append("| " + " | ".join(str(value) for value in row) + " |")
    lines = [
        "RESULTADO:",
        f"- Exactas actuales: {exact}",
        f"- Reconstruidas actuales: {reconstructed}",
        f"- Proxies validados actuales: {validated}",
        f"- Total actual utilizable: {usable_total} de 93",
        f"- Proxies no validados: {unvalidated}",
        f"- Solo referencia antigua: {stale_reference}",
        f"- No disponibles: {unavailable}",
        f"- Numero de dominios en la combinacion seleccionada: {len(selected_sources.get('selected_domains', []))}",
        f"- Cobertura media utilizable por senal: {mean_signal_coverage:.2f}%",
        f"- Empresas procesadas: {manifest['universe_count']}",
        "",
        "# OpenAP 93 Current Maximum-Free Report",
        "",
        "## Combinacion Seleccionada",
        "",
        ", ".join(selected) if selected else "Ninguna fuente supero el contrato completo.",
        "",
        "## Cobertura Por Empresa",
        "",
        (
            f"- Media: {company_coverage.mean():.2f}%"
            if not company_coverage.empty else "- Media: no disponible"
        ),
        (
            f"- Minimo: {company_coverage.min():.2f}%"
            if not company_coverage.empty else "- Minimo: no disponible"
        ),
        (
            f"- Maximo: {company_coverage.max():.2f}%"
            if not company_coverage.empty else "- Maximo: no disponible"
        ),
        "",
        "## Senales Excluidas Del Score Principal",
        "",
        "- Proxies no validados: " + (", ".join(research_only_names) or "ninguno"),
        "- No disponibles: " + (", ".join(unavailable_names) or "ninguna"),
        "- No aplicables al universo actual: " + (", ".join(not_applicable_names) or "ninguna"),
        "",
        "## Fuentes Que Fallaron La Prueba Real",
        "",
        (
            "- " + ", ".join(probe_failures["source_id"].astype(str).tolist())
            if not probe_failures.empty else "- Ninguna"
        ),
        "",
        "## Limites Reales",
        "",
        "- Los proxies sin solapamiento historico suficiente permanecen fuera del score principal.",
        "- Los valores antiguos de OpenAP se usan solo como referencia, nunca como observacion actual.",
        "- Las senales no soportadas se conservan como filas unavailable con motivo explicito.",
        "",
        "## Reejecucion",
        "",
        (
            "Comando completo en GitHub Actions: "
            "`python scripts/run_openap_93_max_free.py "
            "--signals-config config/openap_93/signals_93.yaml run "
            "--base-db inputs/openap_current.duckdb "
            "--output-dir outputs/openap_93_current "
            "--formation-date today --refresh`."
        ),
        (
            "Reejecucion sin red con cache auditada: el mismo comando sustituyendo "
            "`--refresh` por `--offline`."
        ),
        "",
        "## Ejecucion",
        "",
        f"- Formation date: {manifest['formation_at']}",
        f"- Retrieved at: {manifest['retrieved_at']}",
        f"- Runtime seconds: {manifest['runtime_seconds']}",
        (
            "- Tamano total de outputs sin manifiesto: "
            f"{artifact_size_bytes:020d} bytes"
        ),
        f"- OpenAP commit: {manifest['openap_commit']}",
        f"- Base database SHA-256: {manifest['base_database_sha256']}",
        "- Los SHA-256 de todos los outputs estan en `run_manifest.json`.",
        f"- Filas de precios cargadas: {manifest['input_row_counts']['price_rows']}",
        f"- Filas SEC companyfacts cargadas: {manifest['input_row_counts']['companyfact_rows']}",
        f"- Filings 13F seleccionados: {manifest['institutional_inputs']['filing_rows']}",
        f"- Holdings 13F normalizados: {manifest['institutional_inputs']['holding_rows']}",
        (
            "- Holdings 13F con CUSIP unico mapeado: "
            f"{manifest['institutional_inputs']['mapped_holding_rows_pct']:.2f}%"
        ),
        (
            "- Fallos de solicitud OpenFIGI tras reintentos: "
            f"{manifest['institutional_inputs']['request_failed_count']}"
        ),
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
    forward_proxy_certificates: str | Path | None = None,
    forward_proxy_source_manifest: str | Path | None = None,
    forward_proxy_mode: str = "strict",
) -> dict[str, Any]:
    started = time.monotonic()
    formation = pd.Timestamp(formation_at).tz_localize(None)
    if forward_proxy_mode not in {"strict", "advisory"}:
        raise ValueError("forward_proxy_mode must be 'strict' or 'advisory'")
    requested = set(selected_signals) if selected_signals is not None else set(REQUIRED_93)
    unknown = requested - set(REQUIRED_93)
    if unknown:
        raise RuntimeError(f"Unknown requested signals: {sorted(unknown)}")
    retrieved_at = _utcnow()
    database = _find_database(base_database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    public = _load_public_frames(normalized_public_inputs)
    base = _load_base_frames(database, formation, universe_symbols)
    needs_earnings_events = bool(
        requested & (QUARTERLY_IMPLEMENTED_SIGNALS | ANALYST_IMPLEMENTED_SIGNALS)
    )
    earnings_events = (
        build_earnings_events(
            base["master"],
            base["submissions"],
            base["analyst"],
            base["prices"],
        )
        if needs_earnings_events
        else pd.DataFrame()
    )

    results: list[pd.DataFrame] = []
    if selected_signals is None or requested & MARKET_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_market_signals(
                base["master"],
                base["prices"],
                public["ff3_daily"],
                public["ff3_monthly"],
                public["liquidity_monthly"],
                public["vix_daily"],
                formation_at=formation,
                concept_inputs=base["concepts"],
                ff48_sic_codes=public["ff48_sic_codes"],
            )
        )
    if selected_signals is None or requested & ACCOUNTING_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_accounting_signals(
                base["master"],
                base["concepts"],
                formation_at=formation,
                gnp_deflator=_gnp_deflator(public["gnp_deflator"], formation),
            )
        )
    if selected_signals is None or requested & ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_advanced_accounting_signals(
                base["master"],
                base["companyfacts"],
                base["submissions"],
                base["prices"],
                public["gnp_deflator"],
                public["ff48_sic_codes"],
                formation_at=formation,
            )
        )
    if selected_signals is None or requested & QUARTERLY_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_quarterly_signals(
                base["master"],
                base["companyfacts"],
                base["prices"],
                public["ff3_daily"],
                formation_at=formation,
                earnings_events=earnings_events,
            )
        )
    if selected_signals is None or requested & ANALYST_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_analyst_signals(
                base["master"],
                base["analyst"],
                base["companyfacts"],
                formation_at=formation,
                earnings_events=earnings_events,
            )
        )
    if selected_signals is None or requested & EVENT_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_event_signals(
                base["master"], base["prices"], formation_at=formation
            )
        )
    if selected_signals is None or requested & SHORT_INTEREST_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_short_interest_signals(
                base["master"], base["analyst"], formation_at=formation
            )
        )
    if selected_signals is None or requested & INSTITUTIONAL_IMPLEMENTED_SIGNALS:
        results.append(
            calculate_institutional_signals(
                base["master"],
                base["prices"],
                base["companyfacts"],
                base["concepts"],
                base["analyst"],
                public["sec_13f_filings"],
                public["sec_13f_holdings"],
                public["openfigi_cusip_map"],
                formation_at=formation,
            )
        )
    signals = _normalize_signal_results(
        results, base["master"], registry, formation, retrieved_at
    )
    certificates = load_forward_proxy_certificates(forward_proxy_certificates)
    if forward_proxy_certificates is not None and forward_proxy_source_manifest is None:
        raise RuntimeError(
            "forward_proxy_source_manifest is required when certificates are supplied"
        )
    source_manifest_hash = (
        _sha256(Path(forward_proxy_source_manifest))
        if forward_proxy_source_manifest is not None
        else ""
    )
    proxy_formula_hashes = (
        formula_hashes_from_source_manifest(
            forward_proxy_source_manifest,
            repository_root=Path(__file__).resolve().parents[2],
        )
        if forward_proxy_source_manifest is not None
        else {}
    )
    signals = apply_forward_proxy_certificates_to_signals(
        signals,
        certificates,
        source_manifest_sha256=source_manifest_hash,
        formula_hashes=proxy_formula_hashes,
    )
    if selected_signals is not None:
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

    validation = build_validation_report(
        signals,
        openap_reference_sample=public["openap_reference_sample"],
    )
    coverage = build_coverage_report(signals, registry, validation)
    score_table = build_score_table(
        base["features"],
        base["metadata"],
        signals,
        forward_proxy_mode=forward_proxy_mode,
    )
    institutional_audit, institutional_payload = _institutional_input_audit(public)

    signals.to_parquet(output / "signals_93_current.parquet", index=False, compression="zstd")
    signals.to_csv(output / "signals_93_current.csv", index=False)
    score_table.to_parquet(output / "score_185_current.parquet", index=False, compression="zstd")
    score_table.to_csv(output / "score_185_current.csv", index=False)
    coverage.to_csv(output / "coverage_93.csv", index=False)
    validation.to_csv(output / "validation_per_signal.csv", index=False)
    institutional_audit.to_csv(output / "institutional_input_audit.csv", index=False)
    pd.DataFrame(columns=["signal", "month", "paired_observations", "spearman"]).to_parquet(
        output / "validation_per_month.parquet", index=False, compression="zstd"
    )
    (output / "validation_summary.md").write_text(
        "# Validation Summary\n\n"
        "The latest official OpenAP firm-level archive was downloaded and "
        "inspected. It identifies observations with `permno` and `yyyymm`; "
        "Aurora's free current universe uses CIK and ticker. No free authorized "
        "point-in-time identity crosswalk was available, so zero unpaired or "
        "stale values were used to validate or promote a proxy.\n",
        encoding="utf-8",
    )

    reference_metadata_path = (
        Path(normalized_public_inputs) / "openap_reference_metadata.json"
    )
    _copy_report(reference_metadata_path, output / "openap_reference_metadata.json")

    probe = Path(source_probe_dir)
    for name in (
        "source_probe_results.csv",
        "source_symbol_probe_results.csv",
        "source_coverage_matrix.csv",
        "source_ablation.csv",
        "selected_sources.json",
        "sources.lock.json",
    ):
        _copy_report(probe / name, output / name)
    if not (probe / "evidence" / "source_tests").is_dir():
        raise RuntimeError("Required per-source evidence directory is missing")
    shutil.copytree(probe / "evidence", output / "evidence", dirs_exist_ok=True)
    selected_sources = json.loads((output / "selected_sources.json").read_text(encoding="utf-8"))
    source_probes = pd.read_csv(output / "source_probe_results.csv")

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
        "input_row_counts": base["load_audit"],
        "public_input_row_counts": {
            name: int(len(frame)) for name, frame in sorted(public.items())
        },
        "institutional_inputs": institutional_payload,
        "fidelity_counts": {
            fidelity.value: int(
                coverage["fidelity_class"].eq(fidelity.value).sum()
            )
            for fidelity in FidelityClass
        },
        "current_usable_signal_count": int(coverage["current_usable"].sum()),
        "forward_proxy_certificates_loaded": len(certificates),
        "forward_proxy_signals_certified": int(
            signals.loc[
                signals["signal"].isin(FIVE_FORWARD_PROXY_SIGNALS)
                & signals["certificate_status"].eq("certified"),
                "signal",
            ].nunique()
        ),
        "forward_proxy_source_manifest_sha256": source_manifest_hash,
        "forward_proxy_mode": forward_proxy_mode,
    }
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
        "openap_reference_metadata": json.loads(
            (output / "openap_reference_metadata.json").read_text(encoding="utf-8")
        ),
        "signal_formulas": {
            name: {
                "openap_script": spec.openap_script,
                "required_inputs": list(spec.required_inputs),
                "candidate_sources": list(spec.candidate_sources),
                "notes": spec.notes,
            }
            for name, spec in registry.items()
        },
        "institutional_inputs": institutional_payload,
        "generated_at": retrieved_at,
    }
    (output / "data_lineage.json").write_text(
        json.dumps(lineage, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    failures = {
        "signals": coverage.loc[~coverage["current_usable"]][
            ["signal", "fidelity_class", "reason_if_missing"]
        ].to_dict(orient="records"),
        "source_probe_failures": source_probes.loc[
            ~source_probes["probe_ok"].fillna(False),
            ["source_id", "status_code", "error"],
        ].to_dict(orient="records"),
        "institutional_mapping": {
            "status_counts": institutional_payload["mapping_status_counts"],
            "request_failed_count": institutional_payload["request_failed_count"],
            "ambiguous_count": institutional_payload["ambiguous_count"],
            "no_common_stock_match_count": institutional_payload[
                "no_common_stock_match_count"
            ],
            "unresolved_samples": public["openfigi_cusip_map"].loc[
                ~public["openfigi_cusip_map"]["mapping_status"].eq("mapped_unique"),
                ["cusip", "mapping_status", "warning"],
            ].head(100).to_dict(orient="records"),
        },
        "critical_failures": [],
        "generated_at": retrieved_at,
    }
    (output / "failures.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    _write_final_report(
        output / "FINAL_REPORT.md",
        coverage,
        score_table,
        selected_sources,
        manifest,
        source_probes,
    )
    output_total_bytes = sum(
        path.stat().st_size
        for path in output.rglob("*")
        if path.is_file() and path.name != "run_manifest.json"
    )
    _write_final_report(
        output / "FINAL_REPORT.md",
        coverage,
        score_table,
        selected_sources,
        manifest,
        source_probes,
        artifact_size_bytes=output_total_bytes,
    )
    hashes: dict[str, str] = {}
    verified_output_total_bytes = 0
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "run_manifest.json":
            relative = path.relative_to(output).as_posix()
            hashes[relative] = _sha256(path)
            verified_output_total_bytes += path.stat().st_size
    if verified_output_total_bytes != output_total_bytes:
        raise RuntimeError("Final report changed the fixed-width artifact byte count")
    manifest["output_hashes"] = hashes
    manifest["output_total_bytes_excluding_manifest"] = verified_output_total_bytes
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return manifest


__all__ = [
    "IMPLEMENTED_SIGNALS",
    "REQUIRED_SIGNAL_COLUMNS",
    "SCORE_VARIANTS",
    "build_coverage_report",
    "build_score_table",
    "build_validation_report",
    "apply_forward_proxy_certificates_to_signals",
    "load_forward_proxy_certificates",
    "run_current_pipeline",
]
