"""Fail-closed loaders for the six executed OpenAP 149 current batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd


RUN_URL_PREFIX = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
)
FORMULA_INVENTORY_SHA256 = (
    "44de0c0563baace9b4d31118a13ae8a06ea55a87c19ca0ab75841e266efe064d"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class CurrentBatchContract:
    """Immutable evidence contract for one already executed current batch."""

    batch_id: str
    run_id: int
    csv_filename: str
    manifest_filename: str
    csv_sha256: str
    expected_signals: tuple[str, ...]
    expected_rows: int
    expected_usable_rows: int
    expected_sources: tuple[tuple[str, str], ...] = ()
    expected_formula_ids: tuple[tuple[str, str], ...] = ()
    expected_formula_sha256: tuple[tuple[str, str], ...] = ()
    expected_signal_rows: tuple[tuple[str, int], ...] = ()
    expected_signal_usable_rows: tuple[tuple[str, int], ...] = ()
    manifest_row_count_key: str = ""
    manifest_usable_count_key: str = ""
    manifest_signal_key: str = ""
    manifest_signal_list_key: str = ""
    manifest_signal_usable_counts_key: str = ""
    manifest_output_hashes_key: str = ""
    manifest_formula_sha256_key: str = ""
    manifest_records_key: str = ""
    manifest_formation_key: str = "formation_at"
    required_false_manifest_fields: tuple[str, ...] = ()
    required_zero_manifest_fields: tuple[str, ...] = ()
    expected_manifest_values: tuple[tuple[str, object], ...] = ()
    formula_inventory_sha256: str | None = FORMULA_INVENTORY_SHA256
    allow_missing_current_usable: bool = False
    allow_missing_strict_score_eligible: bool = False
    allow_missing_formula_sha256: bool = False


_COMPANYFACTS_SIGNALS = (
    "Accruals",
    "BookLeverage",
    "Cash",
    "ChAssetTurnover",
    "ChInvIA",
    "ChTax",
    "CompositeDebtIssuance",
    "ConvDebt",
    "DebtIssuance",
    "DelCOA",
    "DelCOL",
    "DelDRC",
    "DelEqu",
    "DelFINL",
    "DelLTI",
    "DelNetFin",
    "DivOmit",
    "DivSeason",
    "EarningsConsistency",
    "EarningsSurprise",
    "FirmAge",
    "GP",
    "GrSaleToGrInv",
    "GrSaleToGrOverhead",
    "Herf",
    "HerfAsset",
    "HerfBE",
    "InvGrowth",
    "Investment",
    "NOA",
    "NetDebtFinance",
    "NetEquityFinance",
    "OPLeverage",
    "OperProf",
    "OperProfRD",
    "RDAbility",
    "RDcap",
    "RevenueSurprise",
    "ShareIss1Y",
    "ShareIss5Y",
    "ShareRepurchase",
    "SurpriseRD",
    "Tax",
    "TotalAccruals",
    "XFIN",
    "roaq",
    "sinAlgo",
    "tang",
)


CURRENT_BATCH_CONTRACTS: dict[str, CurrentBatchContract] = {
    "sec_companyfacts": CurrentBatchContract(
        batch_id="sec_companyfacts",
        run_id=31392473937,
        csv_filename="openap_149_sec_companyfacts_current.csv",
        manifest_filename="openap_149_sec_companyfacts_manifest.json",
        csv_sha256=(
            "7eda9f626c80ca38bfebfd47001cc47a83d4d5080abda6517d76f62f0d2d19ca"
        ),
        expected_signals=_COMPANYFACTS_SIGNALS,
        expected_rows=95936,
        expected_usable_rows=95936,
        expected_sources=tuple(
            (signal, "sec_edgar") for signal in _COMPANYFACTS_SIGNALS
        ),
        manifest_row_count_key="current_value_rows",
        manifest_signal_list_key="signals_calculated",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
            "validation_used_for_selection",
        ),
        required_zero_manifest_fields=("cost_eur",),
        expected_manifest_values=(
            ("signal_count", 48),
            ("source_run_id", 31388342037),
        ),
        allow_missing_strict_score_eligible=True,
    ),
    "finra_short_interest": CurrentBatchContract(
        batch_id="finra_short_interest",
        run_id=31384007094,
        csv_filename="openap_149_finra_short_interest_current.csv",
        manifest_filename="openap_149_finra_short_interest_manifest.json",
        csv_sha256=(
            "f179e3274709b78902f38e4a5cd06a55502860f8862f757c8bb7eaa7ce99c545"
        ),
        expected_signals=("IO_ShortInterest", "ShortInterest"),
        expected_rows=2989,
        expected_usable_rows=2989,
        expected_sources=(
            (
                "IO_ShortInterest",
                "finra_equity_short_interest|sec_edgar|sec_13f|openfigi_public",
            ),
            ("ShortInterest", "finra_equity_short_interest|sec_edgar"),
        ),
        expected_formula_ids=(
            (
                "IO_ShortInterest",
                "openap_io_shortinterest_finra_sec13f_current_reconstruction",
            ),
            (
                "ShortInterest",
                "openap_shortinterest_finra_sec_current_proxy",
            ),
        ),
        expected_formula_sha256=(
            (
                "IO_ShortInterest",
                "716310d258802f2a9bc5cf3f02ae012b3e59908a932c75dd5a0701833e222b26",
            ),
            (
                "ShortInterest",
                "25baaf9fd432a4b4805e57cddfb7cb7882eddf8ea27d3cde5b502c304d932b94",
            ),
        ),
        expected_signal_usable_rows=(
            ("IO_ShortInterest", 1),
            ("ShortInterest", 2988),
        ),
        manifest_row_count_key="current_value_rows",
        manifest_signal_usable_counts_key="current_value_signal_counts",
        manifest_formula_sha256_key="formula_sha256",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
            "validation_used_for_selection",
        ),
        required_zero_manifest_fields=("cost_eur",),
        expected_manifest_values=(("source_run_id", 31270341796),),
        allow_missing_strict_score_eligible=True,
    ),
    "realestate": CurrentBatchContract(
        batch_id="realestate",
        run_id=31384049772,
        csv_filename="openap_149_realestate_current.csv",
        manifest_filename="openap_149_realestate_summary.json",
        csv_sha256=(
            "bb9dc9d9525c2371b783dbdb095c79af93f25dda56f6efdac13a1e867e1d5b0a"
        ),
        expected_signals=("realestate",),
        expected_rows=7,
        expected_usable_rows=7,
        expected_sources=(("realestate", "sec_edgar"),),
        expected_formula_ids=(("realestate", "realestate"),),
        manifest_row_count_key="current_values_computed",
        manifest_signal_key="signal",
        manifest_records_key="records",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
            "validation_used_for_selection",
        ),
        required_zero_manifest_fields=("cost_eur",),
        expected_manifest_values=(
            ("source_run_id", 31270341796),
            ("raw_issuers_acquired", 7),
            ("minimum_industry_observations", 5),
            ("proxy_used", True),
            ("fidelity", "reconstructed_not_strict"),
        ),
        formula_inventory_sha256=None,
        allow_missing_current_usable=True,
        allow_missing_strict_score_eligible=True,
        allow_missing_formula_sha256=True,
    ),
    "exchange_switch": CurrentBatchContract(
        batch_id="exchange_switch",
        run_id=31389285731,
        csv_filename="openap_149_sec_exch_switch_current.csv",
        manifest_filename="sec_listing_identity_manifest.json",
        csv_sha256=(
            "aff9d7ca77951d870169caae10fb4984805e09771b1fecf6a4573969d7b8beea"
        ),
        expected_signals=("ExchSwitch",),
        expected_rows=7659,
        expected_usable_rows=2869,
        expected_sources=(
            ("ExchSwitch", "sec_edgar_notes|sec_company_tickers_exchange"),
        ),
        expected_formula_ids=(
            ("ExchSwitch", "openap_exchswitch_current_exchange_lag_1_12"),
        ),
        expected_formula_sha256=(
            (
                "ExchSwitch",
                "b6947fcace7abc2aa1d12f1f04bcd01a8151da7a8a4bfe15a9e56b8a294e6b5b",
            ),
        ),
        manifest_row_count_key="exchange_switch_rows",
        manifest_usable_count_key="exchange_switch_current_value_rows",
        manifest_signal_key="signal",
        manifest_output_hashes_key="output_sha256",
        manifest_formula_sha256_key="formula_sha256",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
        ),
        expected_manifest_values=(
            ("implementation_sha", "85d3cd6cfeefae9f2d6646326679b4ea686b7ac5"),
            ("current_signal_computed", True),
            ("historical_ticker_interval_verified", False),
            ("market_bars_acquired", False),
            ("notes_access_complete", False),
        ),
    ),
    "field_ritter_ipo": CurrentBatchContract(
        batch_id="field_ritter_ipo",
        run_id=31395454942,
        csv_filename="openap_149_field_ritter_ipo_current.csv",
        manifest_filename="openap_149_field_ritter_ipo_manifest.json",
        csv_sha256=(
            "f78ed07e45376b57918c9fb5f6d7239fdacf5e09bd396a1092d7d763a7faf53e"
        ),
        expected_signals=("AgeIPO", "IndIPO", "RDIPO"),
        expected_rows=13149,
        expected_usable_rows=1401,
        expected_sources=tuple(
            (signal, "field_ritter_ipo|openfigi|sec_edgar")
            for signal in ("AgeIPO", "IndIPO", "RDIPO")
        ),
        expected_formula_ids=(
            ("AgeIPO", "openap_ageipo_field_ritter_year_age_3_36m_min100"),
            ("IndIPO", "openap_indipo_field_ritter_calendar_month_3_36"),
            ("RDIPO", "openap_rdipo_field_ritter_sec_explicit_rd_zero_7_36m"),
        ),
        expected_formula_sha256=(
            (
                "AgeIPO",
                "e3e6bb214aab63d92c5cbe278462c016d588ab61383cdea8c637b9c12f3f30b3",
            ),
            (
                "IndIPO",
                "351163e16d519066360d6f598ecbdc9779de57fe5620564f67afbd01b1c0c37b",
            ),
            (
                "RDIPO",
                "a6aa23c8388f49a16f710a70835b07be21a043193169704d6ce2b37ba4d3a568",
            ),
        ),
        expected_signal_rows=(
            ("AgeIPO", 4383),
            ("IndIPO", 4383),
            ("RDIPO", 4383),
        ),
        expected_signal_usable_rows=(
            ("AgeIPO", 0),
            ("IndIPO", 701),
            ("RDIPO", 700),
        ),
        manifest_row_count_key="current_output_rows",
        manifest_usable_count_key="finite_current_value_rows",
        manifest_signal_usable_counts_key="finite_current_value_counts",
        manifest_output_hashes_key="output_sha256",
        manifest_formula_sha256_key="formula_sha256",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
            "validation_used_for_selection",
        ),
        expected_manifest_values=(
            ("implementation_sha", "a579ba3f19e6b0f944b8c021b17e6301bc34d2f3"),
            ("field_ritter_raw_workbook_in_output", False),
        ),
    ),
    "spinoff": CurrentBatchContract(
        batch_id="spinoff",
        run_id=31393646423,
        csv_filename="openap_149_sec_spinoff_current.csv",
        manifest_filename="openap_149_sec_spinoff_manifest.json",
        csv_sha256=(
            "c1ccf515d0866e54988f3823a578bd98d93b027ffbdc14d9000d5692cba16717"
        ),
        expected_signals=("Spinoff",),
        expected_rows=5156,
        expected_usable_rows=8,
        expected_sources=(("Spinoff", "sec_edgar_submissions_and_filings"),),
        expected_formula_ids=(
            ("Spinoff", "openap_spinoff_completed_event_age_le_24"),
        ),
        expected_formula_sha256=(
            (
                "Spinoff",
                "8ab61e7a77f8d93bf0d53647d17efa8d27f6072d3e113c5920810ce182d1ab7b",
            ),
        ),
        manifest_row_count_key="current_output_rows",
        manifest_usable_count_key="finite_current_value_rows",
        manifest_signal_key="signal",
        manifest_output_hashes_key="output_sha256",
        manifest_formula_sha256_key="formula_sha256",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
        ),
        expected_manifest_values=(
            ("implementation_sha", "59efca9b5302bada88c6002add8693223bdbac27"),
            ("current_signal_computed", True),
            ("raw_filing_documents_retained", False),
        ),
    ),
}


def _find_one(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {filename} under {root}, found {len(matches)}"
        )
    return matches[0]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid current-batch manifest: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"current-batch manifest must be an object: {path.name}")
    return payload


def _strict_int(value: Any, label: str) -> int:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric) or not float(numeric).is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(numeric)


def _bool_value(value: Any, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{label} must be an explicit boolean")


def _bool_series(series: pd.Series, label: str) -> pd.Series:
    return series.map(lambda value: _bool_value(value, label)).astype(bool)


def _mapping(entries: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    result = dict(entries)
    if len(result) != len(entries):
        raise ValueError("current-batch contract contains duplicate mapping keys")
    return result


def _require_sha256(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return normalized


def _manifest_value_matches(actual: Any, expected: object, label: str) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, (bool, np.bool_)) and bool(actual) is expected
    if isinstance(expected, int):
        try:
            return _strict_int(actual, label) == expected
        except ValueError:
            return False
    return actual == expected


def _validate_manifest(
    manifest: dict[str, Any],
    frame: pd.DataFrame,
    contract: CurrentBatchContract,
    *,
    csv_sha256: str,
    expected_formula_inventory_sha256: str,
) -> None:
    for key in contract.required_false_manifest_fields:
        if key not in manifest or _bool_value(manifest[key], key):
            raise ValueError(f"manifest safety gate is not false: {key}")
    for key in contract.required_zero_manifest_fields:
        if key not in manifest or _strict_int(manifest[key], key) != 0:
            raise ValueError(f"manifest safety counter is not zero: {key}")
    for key, expected in contract.expected_manifest_values:
        if key not in manifest or not _manifest_value_matches(
            manifest[key], expected, key
        ):
            raise ValueError(f"manifest contract mismatch: {key}")

    if contract.manifest_row_count_key:
        rows = _strict_int(
            manifest.get(contract.manifest_row_count_key),
            contract.manifest_row_count_key,
        )
        if rows != contract.expected_rows:
            raise ValueError("manifest row count does not match the contract")
    if contract.manifest_usable_count_key:
        usable = _strict_int(
            manifest.get(contract.manifest_usable_count_key),
            contract.manifest_usable_count_key,
        )
        if usable != contract.expected_usable_rows:
            raise ValueError("manifest usable count does not match the contract")

    if contract.manifest_signal_key:
        if manifest.get(contract.manifest_signal_key) not in set(
            contract.expected_signals
        ) or len(contract.expected_signals) != 1:
            raise ValueError("manifest signal does not match the contract")
    if contract.manifest_signal_list_key:
        signals = manifest.get(contract.manifest_signal_list_key)
        if (
            not isinstance(signals, list)
            or not all(isinstance(signal, str) for signal in signals)
            or set(signals) != set(contract.expected_signals)
            or len(signals) != len(contract.expected_signals)
        ):
            raise ValueError("manifest signal list does not match the contract")

    expected_usable_counts = _mapping(contract.expected_signal_usable_rows)
    if contract.manifest_signal_usable_counts_key:
        counts = manifest.get(contract.manifest_signal_usable_counts_key)
        if not isinstance(counts, dict) or not set(counts).issubset(
            expected_usable_counts
        ):
            raise ValueError("manifest signal usable counts are invalid")
        actual = {
            signal: _strict_int(counts.get(signal, 0), f"{signal} usable count")
            for signal in expected_usable_counts
        }
        if actual != expected_usable_counts:
            raise ValueError("manifest signal usable counts do not match")

    if contract.manifest_output_hashes_key:
        hashes = manifest.get(contract.manifest_output_hashes_key)
        if (
            not isinstance(hashes, dict)
            or hashes.get(contract.csv_filename) != csv_sha256
        ):
            raise ValueError("manifest output CSV SHA-256 does not match")

    expected_formula_hashes = _mapping(contract.expected_formula_sha256)
    if contract.manifest_formula_sha256_key:
        declared = manifest.get(contract.manifest_formula_sha256_key)
        if isinstance(declared, dict):
            normalized = {str(key): str(value) for key, value in declared.items()}
        elif len(expected_formula_hashes) == 1:
            normalized = {next(iter(expected_formula_hashes)): str(declared)}
        else:
            raise ValueError("manifest formula SHA-256 contract is invalid")
        if normalized != expected_formula_hashes:
            raise ValueError("manifest formula SHA-256 does not match")

    if contract.formula_inventory_sha256 is not None:
        if (
            expected_formula_inventory_sha256
            != contract.formula_inventory_sha256
            or manifest.get("formula_inventory_sha256")
            != contract.formula_inventory_sha256
        ):
            raise ValueError("formula inventory SHA-256 does not match")

    if contract.manifest_records_key:
        records = manifest.get(contract.manifest_records_key)
        if not isinstance(records, list) or len(records) != len(frame):
            raise ValueError("manifest records do not match current rows")
        if not all(isinstance(record, dict) for record in records):
            raise ValueError("manifest records must all be objects")
        record_ids = {str(record.get("security_id", "")) for record in records}
        frame_ids = set(frame["security_id"].astype(str))
        if record_ids != frame_ids or any(
            _bool_value(record.get("strict_score_eligible"), "record strict")
            or not _bool_value(
                record.get("current_signal_computed"),
                "record current_signal_computed",
            )
            for record in records
        ):
            raise ValueError("manifest records violate their current-row contract")


def _validate_frame(
    frame: pd.DataFrame,
    manifest: dict[str, Any],
    contract: CurrentBatchContract,
) -> tuple[pd.DataFrame, bool, bool]:
    required = {
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
        "source_id",
        "source_url",
        "formula_id",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"current batch missing columns: {sorted(missing)}")
    frame = frame.copy()

    normalized_current = False
    if "current_usable" not in frame:
        if not contract.allow_missing_current_usable:
            raise ValueError("current batch missing current_usable gate")
        frame["current_usable"] = True
        normalized_current = True
    normalized_strict = False
    if "strict_score_eligible" not in frame:
        if not contract.allow_missing_strict_score_eligible:
            raise ValueError("current batch missing strict_score_eligible gate")
        frame["strict_score_eligible"] = False
        normalized_strict = True
    if "formula_sha256" not in frame:
        if not contract.allow_missing_formula_sha256:
            raise ValueError("current batch missing formula_sha256")
        frame["formula_sha256"] = ""

    usable = _bool_series(frame["current_usable"], "current_usable")
    strict = _bool_series(
        frame["strict_score_eligible"], "strict_score_eligible"
    )
    frame["current_usable"] = usable
    frame["strict_score_eligible"] = strict
    if strict.any():
        raise ValueError("current batch attempts to activate strict eligibility")

    signals = set(frame["signal"].dropna().astype(str))
    if signals != set(contract.expected_signals):
        raise ValueError("current batch signal set does not match the contract")
    if len(frame) != contract.expected_rows:
        raise ValueError("current batch row count does not match the contract")
    if int(usable.sum()) != contract.expected_usable_rows:
        raise ValueError(
            "current batch usable row count does not match the contract"
        )

    signal_rows = frame["signal"].astype(str).value_counts().to_dict()
    expected_signal_rows = _mapping(contract.expected_signal_rows)
    if expected_signal_rows and signal_rows != expected_signal_rows:
        raise ValueError("current batch per-signal row counts do not match")
    usable_rows = (
        frame.loc[usable, "signal"].astype(str).value_counts().to_dict()
    )
    usable_rows = {
        signal: int(usable_rows.get(signal, 0))
        for signal in contract.expected_signals
    }
    expected_usable_rows = _mapping(contract.expected_signal_usable_rows)
    if expected_usable_rows and usable_rows != expected_usable_rows:
        raise ValueError("current batch per-signal usable counts do not match")

    identity_columns = ["security_id", "ticker", "cik"]
    if any(
        frame[column].isna().any()
        or frame[column].astype(str).str.strip().eq("").any()
        for column in identity_columns
    ):
        raise ValueError("current batch has incomplete identity")
    key = ["security_id", "signal", "formation_at"]
    if frame.duplicated(key, keep=False).any():
        raise ValueError("current batch has duplicate identity keys")

    values = pd.to_numeric(frame["value"], errors="coerce")
    finite = pd.Series(np.isfinite(values), index=frame.index)
    if not finite.loc[usable].all() or finite.loc[~usable].any():
        raise ValueError("current batch usable values are inconsistent")
    fidelity = frame["fidelity_class"].fillna("").astype(str).str.strip()
    if (
        fidelity.eq("").any()
        or fidelity.loc[usable].eq("unavailable").any()
        or not fidelity.loc[~usable].eq("unavailable").all()
    ):
        raise ValueError("current batch fidelity gates are inconsistent")

    expected_sources = _mapping(contract.expected_sources)
    for signal in contract.expected_signals:
        rows = frame.loc[frame["signal"].astype(str).eq(signal)]
        sources = set(rows["source_id"].fillna("").astype(str))
        if signal in expected_sources and sources != {expected_sources[signal]}:
            raise ValueError(f"current batch source mismatch for {signal}")
        source_urls = rows["source_url"].fillna("").astype(str).str.strip()
        if "" in sources or source_urls.eq("").any():
            raise ValueError(f"current batch source is incomplete for {signal}")

    expected_formula_ids = _mapping(contract.expected_formula_ids)
    expected_formula_hashes = _mapping(contract.expected_formula_sha256)
    for signal in contract.expected_signals:
        rows = frame.loc[frame["signal"].astype(str).eq(signal)]
        formula_ids = set(rows["formula_id"].fillna("").astype(str))
        if "" in formula_ids or len(formula_ids) != 1:
            raise ValueError(f"current batch formula is ambiguous for {signal}")
        if (
            signal in expected_formula_ids
            and formula_ids != {expected_formula_ids[signal]}
        ):
            raise ValueError(f"current batch formula mismatch for {signal}")
        formula_hashes = set(rows["formula_sha256"].fillna("").astype(str))
        if not contract.allow_missing_formula_sha256:
            if len(formula_hashes) != 1 or any(
                _SHA256_RE.fullmatch(value) is None for value in formula_hashes
            ):
                raise ValueError(
                    f"current batch formula SHA-256 is invalid for {signal}"
                )
        if (
            signal in expected_formula_hashes
            and formula_hashes != {expected_formula_hashes[signal]}
        ):
            raise ValueError(f"current batch formula SHA-256 mismatch for {signal}")

    formation = pd.to_datetime(frame["formation_at"], utc=True, errors="coerce")
    if formation.isna().any():
        raise ValueError("current batch has invalid formation timestamps")
    usable_rows_frame = frame.loc[usable]
    usable_formation = formation.loc[usable]
    period_end = pd.to_datetime(
        usable_rows_frame["period_end"], utc=True, errors="coerce"
    )
    available = pd.to_datetime(
        usable_rows_frame["available_at"], utc=True, errors="coerce"
    )
    retrieved = pd.to_datetime(
        usable_rows_frame["retrieved_at"], utc=True, errors="coerce"
    )
    if (
        period_end.isna().any()
        or available.isna().any()
        or retrieved.isna().any()
    ):
        raise ValueError("current batch usable rows have invalid timestamps")
    if (
        (period_end > usable_formation).any()
        or (available > usable_formation).any()
        or (available > retrieved).any()
    ):
        raise ValueError("current batch has lookahead timestamps")
    filed_text = usable_rows_frame["filed_at"].fillna("").astype(str).str.strip()
    filed_mask = filed_text.ne("")
    filed = pd.to_datetime(filed_text.loc[filed_mask], utc=True, errors="coerce")
    if filed.isna().any() or (filed > available.loc[filed_mask]).any():
        raise ValueError("current batch has lookahead filing timestamps")

    manifest_formation = pd.to_datetime(
        manifest.get(contract.manifest_formation_key),
        utc=True,
        errors="coerce",
    )
    if pd.isna(manifest_formation) or not formation.eq(manifest_formation).all():
        raise ValueError("current batch formation does not match its manifest")
    return frame, normalized_current, normalized_strict


def load_verified_current_batch(
    root: Path,
    *,
    contract: CurrentBatchContract,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    """Load one current batch only after its complete contract is verified."""

    expected_run_url = f"{RUN_URL_PREFIX}{contract.run_id}"
    if evidence_run_url != expected_run_url:
        raise ValueError(
            f"evidence run URL must be the pinned run for {contract.batch_id}"
        )
    expected_formula_hash = _require_sha256(
        expected_formula_inventory_sha256,
        "expected formula inventory",
    )
    csv_path = _find_one(root, contract.csv_filename)
    manifest_path = _find_one(root, contract.manifest_filename)
    csv_hash = _sha256_file(csv_path)
    if csv_hash != contract.csv_sha256:
        raise ValueError(f"CSV SHA-256 mismatch for {contract.batch_id}")
    manifest = _read_manifest(manifest_path)
    frame = pd.read_csv(csv_path, low_memory=False)
    frame, normalized_current, normalized_strict = _validate_frame(
        frame,
        manifest,
        contract,
    )
    _validate_manifest(
        manifest,
        frame,
        contract,
        csv_sha256=csv_hash,
        expected_formula_inventory_sha256=expected_formula_hash,
    )
    evidence = {
        "batch_id": contract.batch_id,
        "run_id": contract.run_id,
        "run_url": evidence_run_url,
        "csv_sha256": csv_hash,
        "manifest_sha256": _sha256_file(manifest_path),
        "formula_inventory_sha256": expected_formula_hash,
        "formula_inventory_manifest_bound": (
            contract.formula_inventory_sha256 is not None
        ),
        "signals": sorted(contract.expected_signals),
        "rows": int(len(frame)),
        "current_usable_rows": int(frame["current_usable"].sum()),
        "strict_score_increment": 0,
        "normalized_missing_current_usable": normalized_current,
        "normalized_missing_strict_score_eligible": normalized_strict,
    }
    return frame, [csv_path, manifest_path], evidence


def _load_named(
    name: str,
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return load_verified_current_batch(
        root,
        contract=CURRENT_BATCH_CONTRACTS[name],
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_sec_companyfacts_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "sec_companyfacts",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_finra_short_interest_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "finra_short_interest",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_realestate_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "realestate",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_exchange_switch_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "exchange_switch",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_field_ritter_ipo_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "field_ritter_ipo",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )


def load_verified_spinoff_batch(
    root: Path,
    *,
    evidence_run_url: str,
    expected_formula_inventory_sha256: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, object]]:
    return _load_named(
        "spinoff",
        root,
        evidence_run_url=evidence_run_url,
        expected_formula_inventory_sha256=expected_formula_inventory_sha256,
    )
