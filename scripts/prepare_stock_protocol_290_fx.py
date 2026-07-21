"""Prepare one hash-locked causal FX input for the original-290 merge."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

import pandas as pd


CUTOFF = pd.Timestamp("2026-07-17")
START = pd.Timestamp("2006-01-01")
DOWNLOAD_END_EXCLUSIVE = "2026-07-18"
FX_RATES_NAME = "stock-protocol-290-fx-rates.csv"
FX_LOCK_NAME = "stock-protocol-290-fx-source-lock.json"
SOURCE_PROVIDER = "Yahoo Finance historical FX via yfinance"
SOURCE_URL = "https://query1.finance.yahoo.com/"
REQUIRED_SOURCE_ROLES = {
    "prior_opportunity_audit": (
        29804082610,
        "stock-protocol-all-opportunities-and-realistic-portfolio-audit",
    ),
    "frozen_exact_strategy": (
        29688666475,
        "stock-protocol-exact-irrevocable-oos-results-final",
    ),
}

Downloader = Callable[[list[str], str, str], dict[str, pd.Series]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one(root: Path, name: str) -> Path:
    matches = sorted(Path(root).rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected one {name} below {root}, found {len(matches)}")
    return matches[0]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _download_yahoo(symbols: list[str], start: str, end: str) -> dict[str, pd.Series]:
    import yfinance as yf

    downloaded: dict[str, pd.Series] = {}
    for symbol in symbols:
        data = yf.download(
            symbol,
            start=start,
            end=end,
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
        )
        if data.empty:
            continue
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        column = "Adj Close" if "Adj Close" in data else "Close"
        series = pd.to_numeric(data[column], errors="coerce").dropna()
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        downloaded[symbol] = series
    return downloaded


def _verified_sources(source_lock_path: Path) -> list[dict[str, object]]:
    payload = json.loads(Path(source_lock_path).read_text(encoding="utf-8"))
    if payload.get("cutoff") != CUTOFF.date().isoformat():
        raise ValueError("source lock cutoff does not match the FX cutoff")
    indexed = {
        str(item.get("role")): item
        for item in payload.get("verified_artifacts", [])
        if isinstance(item, dict)
    }
    selected: list[dict[str, object]] = []
    for role, (run_id, name) in REQUIRED_SOURCE_ROLES.items():
        item = indexed.get(role)
        if item is None:
            raise ValueError(f"source lock lacks required role {role}")
        if int(item.get("run_id", -1)) != run_id or item.get("name") != name:
            raise ValueError(f"source lock does not pin the expected {role} artifact")
        digest = str(item.get("digest", "")).lower()
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError(f"source lock has invalid digest for {role}")
        selected.append(
            {
                "role": role,
                "run_id": run_id,
                "name": name,
                "digest": digest,
            }
        )
    return selected


def _known_currencies(metadata_path: Path) -> list[str]:
    metadata = pd.read_csv(metadata_path, dtype=str, keep_default_na=False)
    required = {"currency", "currency_unknown"}
    if missing := required - set(metadata.columns):
        raise ValueError(f"currency metadata lacks columns: {sorted(missing)}")
    known = metadata.loc[~metadata["currency_unknown"].map(_as_bool), "currency"]
    currencies = sorted(
        {
            str(value).strip().upper()
            for value in known
            if str(value).strip() and str(value).strip().lower() != "unknown"
        }
    )
    if "USD" not in currencies:
        currencies.append("USD")
        currencies.sort()
    return currencies


def _normalise_series(series: pd.Series, *, invert: bool) -> pd.Series:
    result = pd.to_numeric(series, errors="coerce").dropna().copy()
    dates = pd.to_datetime(result.index, errors="raise")
    if dates.tz is not None:
        dates = dates.tz_convert(None)
    result.index = dates.normalize()
    result = result.loc[(result.index >= START) & (result.index <= CUTOFF)]
    result = result[~result.index.duplicated(keep="last")].sort_index()
    if invert:
        result = 1.0 / result.replace(0, float("nan"))
    result = pd.to_numeric(result, errors="coerce").dropna()
    if result.empty:
        return result
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in result):
        raise ValueError("FX source contains non-positive or non-finite values")
    return result


def prepare_fx_artifact(
    *,
    audit_root: Path,
    exact_root: Path,
    source_lock_path: Path,
    output_root: Path,
    downloader: Downloader = _download_yahoo,
) -> dict[str, object]:
    """Download each required currency once and freeze the exact merge input."""

    source_artifacts = _verified_sources(Path(source_lock_path))
    metadata_path = _one(Path(audit_root), "symbol_exchange_currency_map.csv")
    audit_manifest = _one(Path(audit_root), "final_artifact_manifest.json")
    exact_manifest = _one(Path(exact_root), "final_artifact_manifest.json")
    currencies = _known_currencies(metadata_path)
    non_usd = [currency for currency in currencies if currency != "USD"]
    pairs = {
        currency: (f"{currency}USD=X", f"USD{currency}=X")
        for currency in non_usd
    }
    symbols = [symbol for currency in non_usd for symbol in pairs[currency]]
    downloaded = downloader(symbols, START.date().isoformat(), DOWNLOAD_END_EXCLUSIVE)

    rows = [
        pd.DataFrame(
            {
                "date": pd.date_range(START, CUTOFF, freq="D"),
                "currency": "USD",
                "usd_per_local": 1.0,
                "source": "identity",
                "source_symbol": "USD",
                "orientation": "USD_identity",
                "cutoff": CUTOFF.date().isoformat(),
            }
        )
    ]
    currency_sources: list[dict[str, object]] = [
        {
            "currency": "USD",
            "source": "identity",
            "source_symbol": "USD",
            "orientation": "USD_identity",
            "start": START.date().isoformat(),
            "end": CUTOFF.date().isoformat(),
            "observations": int((CUTOFF - START).days + 1),
        }
    ]
    for currency in non_usd:
        direct, inverse = pairs[currency]
        selected: tuple[str, str, pd.Series] | None = None
        for source_symbol, orientation, invert in (
            (direct, "USD_per_local_direct", False),
            (inverse, "inverted_local_per_USD", True),
        ):
            if source_symbol not in downloaded:
                continue
            series = _normalise_series(downloaded[source_symbol], invert=invert)
            if not series.empty:
                selected = source_symbol, orientation, series
                break
        if selected is None:
            raise ValueError(f"frozen FX source has no causal rows for {currency}")
        source_symbol, orientation, series = selected
        rows.append(
            pd.DataFrame(
                {
                    "date": series.index,
                    "currency": currency,
                    "usd_per_local": series.to_numpy(),
                    "source": "Yahoo Finance historical FX",
                    "source_symbol": source_symbol,
                    "orientation": orientation,
                    "cutoff": CUTOFF.date().isoformat(),
                }
            )
        )
        currency_sources.append(
            {
                "currency": currency,
                "source": "Yahoo Finance historical FX",
                "source_symbol": source_symbol,
                "orientation": orientation,
                "start": series.index.min().date().isoformat(),
                "end": series.index.max().date().isoformat(),
                "observations": len(series),
            }
        )

    output = Path(output_root)
    if output.exists() and any(output.iterdir()):
        raise ValueError("FX output root must be empty")
    output.mkdir(parents=True, exist_ok=True)
    rates = pd.concat(rows, ignore_index=True).sort_values(
        ["currency", "date"], kind="stable"
    )
    if pd.to_datetime(rates["date"], errors="raise").max() > CUTOFF:
        raise ValueError("FX rates exceed the frozen cutoff")
    rates_path = output / FX_RATES_NAME
    rates.to_csv(rates_path, index=False, date_format="%Y-%m-%d", float_format="%.12g")
    payload: dict[str, object] = {
        "schema_version": 1,
        "cutoff": CUTOFF.date().isoformat(),
        "download_start": START.date().isoformat(),
        "download_end_exclusive": DOWNLOAD_END_EXCLUSIVE,
        "rates_file": FX_RATES_NAME,
        "rates_sha256": _sha256(rates_path),
        "rates_rows": len(rates),
        "currencies": currencies,
        "source_provider": SOURCE_PROVIDER,
        "source_url": SOURCE_URL,
        "source_artifacts": source_artifacts,
        "source_files": {
            "audit_currency_map": {
                "name": metadata_path.name,
                "sha256": _sha256(metadata_path),
            },
            "audit_manifest": {
                "name": audit_manifest.name,
                "sha256": _sha256(audit_manifest),
            },
            "exact_manifest": {
                "name": exact_manifest.name,
                "sha256": _sha256(exact_manifest),
            },
            "source_lock": {
                "name": Path(source_lock_path).name,
                "sha256": _sha256(Path(source_lock_path)),
            },
        },
        "currency_sources": currency_sources,
        "causal_rule": "same-day or latest earlier observation only",
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
    }
    (output / FX_LOCK_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return payload


def verify_fx_artifact(root: Path) -> dict[str, object]:
    """Verify the frozen CSV against its lock before the merge consumes it."""

    artifact_root = Path(root)
    lock_path = artifact_root / FX_LOCK_NAME
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("cutoff") != CUTOFF.date().isoformat():
        raise ValueError("FX artifact lock has the wrong cutoff")
    if payload.get("rates_file") != FX_RATES_NAME:
        raise ValueError("FX artifact lock has the wrong rates file")
    rates_path = artifact_root / FX_RATES_NAME
    if _sha256(rates_path) != payload.get("rates_sha256"):
        raise ValueError("FX rates sha256 does not match the frozen lock")
    rates = pd.read_csv(rates_path)
    required = {"date", "currency", "usd_per_local", "source", "source_symbol"}
    if missing := required - set(rates.columns):
        raise ValueError(f"frozen FX rates lack columns: {sorted(missing)}")
    dates = pd.to_datetime(rates["date"], errors="raise")
    values = pd.to_numeric(rates["usd_per_local"], errors="coerce")
    if dates.max() > CUTOFF:
        raise ValueError("frozen FX rates exceed the cutoff")
    if values.isna().any() or any(
        not math.isfinite(float(value)) or float(value) <= 0 for value in values
    ):
        raise ValueError("frozen FX rates contain invalid values")
    if int(payload.get("rates_rows", -1)) != len(rates):
        raise ValueError("frozen FX row count does not match the lock")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-root", type=Path)
    parser.add_argument("--exact-root", type=Path)
    parser.add_argument("--source-lock", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--verify-root", type=Path)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.verify_root is not None:
        if any(
            value is not None
            for value in (
                args.audit_root,
                args.exact_root,
                args.source_lock,
                args.output_root,
            )
        ):
            parser.error("--verify-root cannot be combined with preparation inputs")
        print(json.dumps(verify_fx_artifact(args.verify_root), sort_keys=True))
        return 0
    if any(
        value is None
        for value in (
            args.audit_root,
            args.exact_root,
            args.source_lock,
            args.output_root,
        )
    ):
        parser.error("preparation requires audit, exact, source-lock, and output roots")
    prepare_fx_artifact(
        audit_root=args.audit_root,
        exact_root=args.exact_root,
        source_lock_path=args.source_lock,
        output_root=args.output_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
