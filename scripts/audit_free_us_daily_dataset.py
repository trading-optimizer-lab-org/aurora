"""Audit a materialized free_us_daily data lake artifact."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_UNIVERSE_COLUMNS = {
    "provider_symbol",
    "canonical_symbol",
    "yfinance_symbol",
    "security_name",
    "asset_type",
    "exchange",
    "source",
}
REQUIRED_PRICE_COLUMNS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
    "source",
    "retrieved_at",
    "symbol",
}
BAD_NAME_RE = re.compile(
    r"\b(?:"
    r"warrants?|rights?|units?|preferred|preferences?|depositary|depository|"
    r"notes?|bonds?|funds?|etfs?|etns?|trusts?|certificates?|adr|gdr|ads|"
    r"receipts?|spac|acquisition\s+(?:corp|company)"
    r")\b",
    re.IGNORECASE,
)


def _read_catalog(dataset_root: Path) -> pd.DataFrame:
    path = dataset_root / "catalog.sqlite"
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as con:
        return pd.read_sql_query("SELECT * FROM downloads", con)


def _issue(kind: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"kind": kind, "severity": severity, "message": message}
    payload.update(extra)
    return payload


def _load_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _audit_universe(dataset_root: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    universe_path = dataset_root / "universe" / "us_stock_like_universe.parquet"
    if not universe_path.exists():
        issues.append(_issue("universe", "critical", "missing universe parquet"))
        return pd.DataFrame(), issues
    universe = _load_parquet(universe_path)
    missing = sorted(REQUIRED_UNIVERSE_COLUMNS - set(universe.columns))
    if missing:
        issues.append(
            _issue("universe", "critical", "missing universe columns", columns=";".join(missing))
        )
    if "canonical_symbol" in universe:
        dupes = universe["canonical_symbol"].astype(str).duplicated(keep=False)
        if dupes.any():
            issues.append(
                _issue("universe", "critical", "duplicate canonical symbols", count=int(dupes.sum()))
            )
    for column in ("provider_symbol", "canonical_symbol", "yfinance_symbol"):
        if column in universe:
            blank = universe[column].isna() | (universe[column].astype(str).str.strip() == "")
            if blank.any():
                issues.append(
                    _issue("universe", "critical", f"blank {column}", count=int(blank.sum()))
                )
    if "security_name" in universe:
        suspicious = universe["security_name"].fillna("").astype(str).str.contains(BAD_NAME_RE)
        if suspicious.any():
            issues.append(
                _issue("universe", "high", "suspicious instrument names", count=int(suspicious.sum()))
            )
    return universe, issues


def _audit_metadata(dataset_root: Path, universe: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    path = dataset_root / "metadata" / "company_metadata.parquet"
    if not path.exists():
        issues.append(_issue("metadata", "high", "missing company metadata parquet"))
        return pd.DataFrame(), issues
    metadata = _load_parquet(path)
    if universe.empty or "canonical_symbol" not in universe or "symbol" not in metadata:
        return metadata, issues
    universe_symbols = set(universe["canonical_symbol"].astype(str))
    metadata_symbols = set(metadata["symbol"].astype(str))
    missing_metadata = sorted(universe_symbols - metadata_symbols)
    extra_metadata = sorted(metadata_symbols - universe_symbols)
    if missing_metadata:
        issues.append(
            _issue("metadata", "medium", "universe symbols without metadata", count=len(missing_metadata))
        )
    if extra_metadata:
        issues.append(
            _issue("metadata", "low", "metadata rows outside universe", count=len(extra_metadata))
        )
    if "market_cap" in metadata:
        cap = pd.to_numeric(metadata["market_cap"], errors="coerce")
        below = metadata[cap.notna() & (cap < 50_000_000)]
        if len(below):
            issues.append(
                _issue("metadata", "high", "metadata market cap below 50M USD", count=int(len(below)))
            )
    foreign = (
        universe[universe["asset_type"] == "FOREIGN_COMMON_STOCK"].copy()
        if "asset_type" in universe
        else pd.DataFrame()
    )
    if not foreign.empty and "market_cap" in metadata:
        foreign_meta = foreign[["canonical_symbol"]].merge(
            metadata,
            how="left",
            left_on="canonical_symbol",
            right_on="symbol",
        )
        missing_cap = pd.to_numeric(foreign_meta["market_cap"], errors="coerce").isna()
        low_cap = pd.to_numeric(foreign_meta["market_cap"], errors="coerce") < 50_000_000
        if missing_cap.any() or low_cap.any():
            issues.append(
                _issue(
                    "metadata",
                    "high",
                    "foreign symbols violate or miss market cap filter",
                    count=int((missing_cap | low_cap).sum()),
                )
            )
    return metadata, issues


def _audit_catalog_and_files(dataset_root: Path, universe: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    catalog = _read_catalog(dataset_root)
    normalized_dir = dataset_root / "normalized"
    normalized_files = {p.stem: p for p in normalized_dir.glob("*.parquet")} if normalized_dir.exists() else {}
    if catalog.empty:
        issues.append(_issue("catalog", "critical", "missing or empty downloads catalog"))
        return catalog, issues
    if "canonical_symbol" in universe:
        universe_symbols = set(universe["canonical_symbol"].astype(str))
        catalog_symbols = set(catalog["symbol"].astype(str))
        missing_catalog = universe_symbols - catalog_symbols
        extra_catalog = catalog_symbols - universe_symbols
        if missing_catalog:
            issues.append(_issue("catalog", "critical", "universe symbols missing from catalog", count=len(missing_catalog)))
        if extra_catalog:
            issues.append(_issue("catalog", "medium", "catalog symbols outside universe", count=len(extra_catalog)))
    ok_catalog = set(catalog.loc[catalog["status"] == "ok", "symbol"].astype(str))
    missing_ok_files = sorted(ok_catalog - set(normalized_files))
    if missing_ok_files:
        issues.append(_issue("files", "critical", "ok catalog rows without normalized parquet", count=len(missing_ok_files)))
    files_without_catalog = sorted(set(normalized_files) - set(catalog["symbol"].astype(str)))
    if files_without_catalog:
        issues.append(_issue("files", "medium", "normalized parquet files outside catalog", count=len(files_without_catalog)))
    return catalog, issues


def _audit_price_files(
    dataset_root: Path,
    catalog: pd.DataFrame,
    *,
    max_rows_out: int = 5000,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    normalized_dir = dataset_root / "normalized"
    if catalog.empty or not normalized_dir.exists():
        return pd.DataFrame(), issues
    for path in sorted(normalized_dir.glob("*.parquet")):
        symbol = path.stem
        try:
            df = pd.read_parquet(path, columns=list(REQUIRED_PRICE_COLUMNS))
        except Exception as exc:
            rows.append({"symbol": symbol, "status": "read_error", "problem": str(exc)})
            continue
        missing = sorted(REQUIRED_PRICE_COLUMNS - set(df.columns))
        problems: list[str] = []
        if missing:
            problems.append("missing_columns:" + ",".join(missing))
        dates = pd.to_datetime(df.get("date"), errors="coerce")
        if dates.isna().any():
            problems.append("invalid_dates")
        if dates.duplicated().any():
            problems.append("duplicate_dates")
        if not dates.is_monotonic_increasing:
            problems.append("dates_not_sorted")
        for col in ("open", "high", "low", "close", "adj_close"):
            values = pd.to_numeric(df.get(col), errors="coerce")
            if values.isna().any():
                problems.append(f"{col}_non_numeric")
            if (values <= 0).any():
                problems.append(f"{col}_non_positive")
        volume = pd.to_numeric(df.get("volume"), errors="coerce")
        if volume.isna().any() or (volume < 0).any():
            problems.append("volume_invalid")
        if (pd.to_numeric(df["high"], errors="coerce") < pd.to_numeric(df["low"], errors="coerce")).any():
            problems.append("high_below_low")
        if "symbol" in df and set(df["symbol"].dropna().astype(str).unique()) - {symbol}:
            problems.append("embedded_symbol_mismatch")
        last_date = dates.max()
        first_date = dates.min()
        if len(dates.dropna()) >= 2:
            max_gap = int(dates.sort_values().diff().dt.days.dropna().max())
        else:
            max_gap = None
        if max_gap is not None and max_gap > 31:
            problems.append("calendar_gap_gt_31d")
        rows.append(
            {
                "symbol": symbol,
                "status": "ok" if not problems else "problem",
                "problem": ";".join(problems),
                "rows": int(len(df)),
                "first_date": first_date.date().isoformat() if pd.notna(first_date) else "",
                "last_date": last_date.date().isoformat() if pd.notna(last_date) else "",
                "max_calendar_gap_days": max_gap,
            }
        )
    report = pd.DataFrame(rows)
    if not report.empty:
        problem_count = int((report["status"] == "problem").sum())
        read_errors = int((report["status"] == "read_error").sum())
        if problem_count:
            issues.append(_issue("prices", "high", "normalized price files with data problems", count=problem_count))
        if read_errors:
            issues.append(_issue("prices", "critical", "normalized price files with read errors", count=read_errors))
    return report, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-price-issue-rows", type=int, default=5000)
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    issues: list[dict[str, Any]] = []
    universe, found = _audit_universe(dataset_root)
    issues.extend(found)
    metadata, found = _audit_metadata(dataset_root, universe)
    issues.extend(found)
    catalog, found = _audit_catalog_and_files(dataset_root, universe)
    issues.extend(found)
    price_report, found = _audit_price_files(
        dataset_root,
        catalog,
        max_rows_out=args.max_price_issue_rows,
    )
    issues.extend(found)

    quality_counts = catalog["status"].value_counts().to_dict() if not catalog.empty and "status" in catalog else {}
    summary = {
        "dataset_root": str(dataset_root),
        "universe_rows": int(len(universe)),
        "metadata_rows": int(len(metadata)),
        "catalog_rows": int(len(catalog)),
        "normalized_files": int(len(list((dataset_root / "normalized").glob("*.parquet"))) if (dataset_root / "normalized").exists() else 0),
        "raw_files": int(len(list((dataset_root / "raw" / "yfinance").glob("*.parquet"))) if (dataset_root / "raw" / "yfinance").exists() else 0),
        "asset_type_counts": universe["asset_type"].value_counts().to_dict() if "asset_type" in universe else {},
        "source_counts": universe["source"].value_counts().to_dict() if "source" in universe else {},
        "download_status_counts": quality_counts,
        "issue_counts_by_severity": pd.Series([i["severity"] for i in issues]).value_counts().to_dict() if issues else {},
        "issues": issues,
    }
    (output_dir / "audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    pd.DataFrame(issues).to_csv(output_dir / "audit_issues.csv", index=False)
    if not catalog.empty:
        catalog.to_csv(output_dir / "catalog_downloads.csv", index=False)
        catalog[catalog["status"] != "ok"].to_csv(output_dir / "non_ok_downloads.csv", index=False)
    if not price_report.empty:
        price_report.head(args.max_price_issue_rows).to_csv(
            output_dir / "price_file_audit_sample.csv",
            index=False,
        )
        price_report[price_report["status"] != "ok"].to_csv(
            output_dir / "price_file_audit_problems.csv",
            index=False,
        )
    if not universe.empty and "security_name" in universe:
        suspicious = universe[universe["security_name"].fillna("").astype(str).str.contains(BAD_NAME_RE)].copy()
        suspicious.to_csv(output_dir / "suspicious_names.csv", index=False)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
