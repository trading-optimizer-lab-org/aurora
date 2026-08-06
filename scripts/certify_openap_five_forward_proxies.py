"""Build frozen train/validation certificates for five OpenAP reconstructions."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.core.execution_policy import require_github_execution  # noqa: E402
from aurora.research.openap_93.forward_proxy_validation import (  # noqa: E402
    ForwardProxyGate,
    certificate_sha256,
    certify_forward_proxy_candidates,
)
from aurora.research.openap_93.official_portfolio_similarity import (  # noqa: E402
    build_official_long_short_spreads,
    build_proxy_spreads,
    download_official_long_short,
)


def _read_frame(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() == ".parquet":
        return pd.read_parquet(source)
    return pd.read_csv(source)


def _file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def run_certification(
    *,
    proxy_panel: str | Path,
    monthly_returns: str | Path,
    official_long_short: str | Path,
    output_dir: str | Path,
    source_manifest: str | Path | None = None,
    train_end: str = "2010-12-31",
    validation_start: str = "2011-01-01",
    validation_end: str = "2020-12-31",
) -> dict[str, object]:
    require_github_execution("OpenAP five forward-proxy certification")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    proxy = _read_frame(proxy_panel)
    monthly = _read_frame(monthly_returns)
    proxy_spreads = build_proxy_spreads(proxy, monthly)
    candidates = proxy_spreads.rename(
        columns={
            "formation_month": "month",
            "proxy_spread_return": "proxy_return",
        }
    )
    official_raw = download_official_long_short(
        output_dir=output,
        archive_path=official_long_short,
    )
    official = build_official_long_short_spreads(official_raw).rename(
        columns={
            "formation_month": "month",
            "official_spread_return": "official_return",
        }
    )
    variant_metadata = proxy.copy()
    if "variant_id" not in variant_metadata.columns:
        variant_metadata["variant_id"] = variant_metadata.get(
            "proxy_formula_id", pd.Series("default", index=variant_metadata.index)
        ).astype("string")
    if "proxy_formula_id" not in variant_metadata.columns:
        variant_metadata["proxy_formula_id"] = variant_metadata["variant_id"]
    manifest_hash = (
        _file_sha256(source_manifest)
        if source_manifest is not None
        else _text_sha256("public-source-manifest-not-supplied")
    )
    identities = candidates[["signal", "variant_id"]].drop_duplicates()
    formula_hashes: dict[tuple[str, str], str] = {}
    source_hashes: dict[tuple[str, str], str] = {}
    for row in identities.itertuples(index=False):
        identity = (str(row.signal), str(row.variant_id))
        formulas = sorted(
            set(
                variant_metadata.loc[
                    variant_metadata["signal"].eq(row.signal)
                    & variant_metadata["variant_id"].eq(row.variant_id),
                    "proxy_formula_id",
                ].astype(str)
            )
        )
        formula_hashes[identity] = _text_sha256("|".join(formulas))
        source_hashes[identity] = manifest_hash

    selected, validation, certificates = certify_forward_proxy_candidates(
        candidates,
        official,
        formula_hashes=formula_hashes,
        source_manifest_hashes=source_hashes,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        gate=ForwardProxyGate(),
    )
    selected.to_csv(output / "forward_proxy_candidate_metrics.csv", index=False)
    validation.to_csv(output / "forward_proxy_validation_metrics.csv", index=False)
    with (output / "forward_proxy_certificates.jsonl").open("w", encoding="utf-8") as handle:
        for certificate in certificates:
            record = asdict(certificate)
            record["certificate_sha256"] = certificate_sha256(certificate)
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
    proxy_spreads.to_csv(output / "forward_proxy_candidate_returns.csv", index=False)
    summary = {
        "signals_evaluated": len(certificates),
        "signals_certified": sum(certificate.passed for certificate in certificates),
        "train_end": train_end,
        "validation_start": validation_start,
        "validation_end": validation_end,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "backtest_enabled": False,
        "partial": False,
    }
    (output / "forward_proxy_certification_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-panel", required=True)
    parser.add_argument("--monthly-returns", required=True)
    parser.add_argument("--official-long-short", required=True)
    parser.add_argument("--source-manifest", default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--train-end", default="2010-12-31")
    parser.add_argument("--validation-start", default="2011-01-01")
    parser.add_argument("--validation-end", default="2020-12-31")
    args = parser.parse_args()
    run_certification(
        proxy_panel=args.proxy_panel,
        monthly_returns=args.monthly_returns,
        official_long_short=args.official_long_short,
        source_manifest=args.source_manifest,
        output_dir=args.output_dir,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
    )


if __name__ == "__main__":
    main()
