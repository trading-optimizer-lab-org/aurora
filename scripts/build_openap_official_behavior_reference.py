"""Build a high-fidelity, source-backed OpenAP behavior reference.

This is intentionally not an independent stock-level reconstruction.  It
mirrors the official monthly long-short returns so that downstream systems can
compare their behavior against the authoritative published target without
mistaking the mirror for a usable stock-scoring proxy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.historical_proxy_validation import FIVE_PROXY_SIGNALS
from aurora.research.openap_93.official_portfolio_similarity import (
    download_official_long_short,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_reference(source: str | Path, output_dir: str | Path) -> dict[str, object]:
    source_path = Path(source)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    official = download_official_long_short(
        output_dir=output,
        archive_path=source_path,
    ).copy()
    official["formation_month"] = pd.to_datetime(official["formation_month"]).dt.strftime("%Y-%m-%d")

    reference = official.rename(columns={"official_return": "reference_return"})
    reference["proxy_return"] = reference["reference_return"]
    reference["proxy_kind"] = "official_source_mirror"
    reference["independent_reconstruction"] = False
    reference["usable_for_stock_scoring"] = False
    reference["source_file"] = str(source_path)
    reference.to_csv(output / "official_behavior_reference_proxy.csv", index=False)

    similarity_rows: list[dict[str, object]] = []
    for signal, group in reference.groupby("signal", sort=True):
        left = pd.to_numeric(group["reference_return"], errors="coerce")
        right = pd.to_numeric(group["proxy_return"], errors="coerce")
        pair = pd.DataFrame({"left": left, "right": right}).dropna()
        identical = bool(pair["left"].equals(pair["right"]))
        pearson = 1.0 if identical else float(pair["left"].corr(pair["right"]))
        spearman = 1.0 if identical else float(pair["left"].rank().corr(pair["right"].rank()))
        mean_abs_error = float((pair["left"] - pair["right"]).abs().mean())
        tracking_error = float((pair["left"] - pair["right"]).std(ddof=1)) if len(pair) > 1 else 0.0
        similarity_rows.append(
            {
                "signal": str(signal),
                "rows": int(len(pair)),
                "pearson": pearson,
                "spearman": spearman,
                "sign_consistency": float((pair["left"].abs().eq(0) | (pair["left"].gt(0) == pair["right"].gt(0))).mean()),
                "mean_abs_error": mean_abs_error,
                "tracking_error": tracking_error,
                "proxy_kind": "official_source_mirror",
                "independent_reconstruction": False,
            }
        )
    similarity = pd.DataFrame(similarity_rows)
    similarity.to_csv(output / "official_behavior_reference_similarity.csv", index=False)

    summary = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "reference_rows": int(len(reference)),
        "similarity_min_pearson": float(similarity["pearson"].min()),
        "similarity_min_spearman": float(similarity["spearman"].min()),
        "similarity_min_sign_consistency": float(similarity["sign_consistency"].min()),
        "proxy_kind": "official_source_mirror",
        "independent_reconstruction": False,
        "usable_for_stock_scoring": False,
        "source_sha256": _sha256(source_path),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
    }
    (output / "official_behavior_reference_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (output / "official_behavior_reference_audit.md").write_text(
        "# OpenAP official behavior reference\n\n"
        "This artifact mirrors the official OpenAP monthly long-short returns.\n"
        "It is the highest-fidelity behavior reference available, but it is not\n"
        "an independent reconstruction and must not be used to score stocks.\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-long-short", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    require_github_execution("OpenAP official behavior reference")
    summary = build_reference(args.official_long_short, args.output_dir)
    pearson_min = summary["similarity_min_pearson"]
    spearman_min = summary["similarity_min_spearman"]
    if not isinstance(pearson_min, (int, float)) or not isinstance(spearman_min, (int, float)):
        raise RuntimeError("Reference similarity summary is not numeric")
    if abs(pearson_min - 1.0) > 1e-12 or abs(spearman_min - 1.0) > 1e-12:
        raise RuntimeError("Official source mirror did not reproduce the official returns exactly")


if __name__ == "__main__":
    main()
