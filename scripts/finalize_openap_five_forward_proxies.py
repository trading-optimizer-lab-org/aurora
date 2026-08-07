"""Assemble the auditable final artifact for the five forward proxies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import pandas as pd
import yaml

from aurora.core.execution_policy import require_github_execution


SIGNALS = ("DivSeason", "AnnouncementReturn", "EarningsStreak", "IndRetBig", "DelNetFin")


def _first(root: Path, name: str) -> Path | None:
    return next(iter(sorted(root.rglob(name))), None)


def _read_csv(path: Path | None) -> pd.DataFrame:
    return pd.read_csv(path) if path is not None and path.is_file() else pd.DataFrame()


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def finalize(
    *,
    certification_dir: str | Path,
    current_dir: str | Path,
    source_manifest: str | Path,
    output_dir: str | Path,
    certification_result: str,
    current_result: str,
) -> dict[str, object]:
    require_github_execution("OpenAP five forward-proxy finalization")
    cert_root = Path(certification_dir)
    current_root = Path(current_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    selected = _read_csv(_first(cert_root, "forward_proxy_candidate_metrics.csv"))
    validation = _read_csv(_first(cert_root, "forward_proxy_validation_metrics.csv"))
    candidate_returns = _read_csv(_first(cert_root, "forward_proxy_candidate_returns.csv"))
    cert_path = _first(cert_root, "forward_proxy_certificates.jsonl")
    certificates = []
    if cert_path is not None:
        certificates = [json.loads(line) for line in cert_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    current_path = _first(current_root, "signals_93_current.csv")
    current = _read_csv(current_path)
    if not current.empty:
        current = current.loc[current["signal"].isin(SIGNALS)].copy()
    for name, frame in (
        ("forward_proxy_candidate_metrics.csv", selected),
        ("forward_proxy_validation_metrics.csv", validation),
    ):
        frame.to_csv(output / name, index=False)
    candidate_returns.to_csv(output / "forward_proxy_candidate_returns.csv", index=False)
    (output / "forward_proxy_certificates.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in certificates),
        encoding="utf-8",
    )
    for name in (
        "score_185_current.csv",
        "score_185_current.parquet",
        "score_185_strict_current.csv",
        "score_185_strict_current.parquet",
        "score_185_advisory_current.csv",
        "score_185_advisory_current.parquet",
    ):
        source = _first(current_root, name)
        if source is not None:
            shutil.copy2(source, output / name.replace("score_185_", "forward_proxy_score_"))

    if current.empty:
        current = pd.DataFrame(
            columns=[
                "ticker",
                "signal",
                "value",
                "current_usable",
                "certificate_status",
                "forward_advisory_usable",
                "forward_advisory_score_weight",
            ]
        )
    current.to_csv(output / "forward_proxy_current_values.csv", index=False)
    current.to_parquet(output / "forward_proxy_current_values.parquet", index=False, compression="zstd")
    strict_mask = current["current_usable"].fillna(False).astype(bool)
    advisory_mask = current.get(
        "forward_advisory_usable",
        pd.Series(False, index=current.index),
    ).fillna(False).astype(bool)
    score_ready = current.loc[strict_mask].copy()
    advisory_ready = current.loc[advisory_mask].copy()
    score_ready.to_csv(output / "forward_proxy_score_ready.csv", index=False)
    advisory_ready.to_csv(output / "forward_proxy_advisory_current.csv", index=False)
    advisory_ready.to_parquet(
        output / "forward_proxy_advisory_current.parquet",
        index=False,
        compression="zstd",
    )
    missing = current.loc[~strict_mask].copy()
    missing.to_csv(output / "forward_proxy_missing_inputs.csv", index=False)

    manifest = yaml.safe_load(Path(source_manifest).read_text(encoding="utf-8"))
    source_rows = []
    for signal, spec in manifest["signals"].items():
        source_rows.append(
            {
                "signal": signal,
                "formula_id": spec["formula_id"],
                "accepted_variants": "|".join(spec.get("accepted_variants", [])),
                "sources": "|".join(spec.get("sources", [])),
                "code": "|".join(spec.get("code", [])),
            }
        )
    pd.DataFrame(source_rows).to_csv(output / "forward_proxy_source_audit.csv", index=False)

    validation_by_signal = {
        str(row["signal"]): row for row in validation.to_dict(orient="records")
    }
    signal_summary = []
    for signal in SIGNALS:
        metrics = validation_by_signal.get(signal, {})
        current_signal = current.loc[current["signal"].eq(signal)] if "signal" in current else pd.DataFrame()
        signal_summary.append(
            {
                "signal": signal,
                "certified": _truthy(metrics.get("passed", False)),
                "common_months": int(metrics.get("common_months", 0) or 0),
                "pearson": metrics.get("pearson"),
                "spearman": metrics.get("spearman"),
                "sign_agreement": metrics.get("sign_agreement"),
                "current_rows": int(len(current_signal)),
                "current_values_available": int(current_signal["value"].notna().sum()) if "value" in current_signal else 0,
                "score_ready_rows": int(score_ready["signal"].eq(signal).sum()) if "signal" in score_ready else 0,
                "advisory_rows": int(advisory_ready["signal"].eq(signal).sum()) if "signal" in advisory_ready else 0,
            }
        )
    current_manifest_path = _first(current_root, "run_manifest.json")
    current_manifest = (
        json.loads(current_manifest_path.read_text(encoding="utf-8"))
        if current_manifest_path is not None
        else {}
    )
    summary = {
        "signals": signal_summary,
        "signals_evaluated": int(len(validation)),
        "signals_certified": int(sum(bool(item["certified"]) for item in signal_summary)),
        "current_values_available": int(current.get("value", pd.Series(dtype=float)).notna().sum()),
        "score_ready_rows": int(len(score_ready)),
        "advisory_rows": int(len(advisory_ready)),
        "forward_proxy_mode": current_manifest.get("forward_proxy_mode", "strict"),
        "certification_job_result": certification_result,
        "current_job_result": current_result,
        "partial": certification_result != "success" or (
            any(item["certified"] for item in signal_summary) and current_result != "success"
        ),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "backtest_enabled": False,
        "exact_replication_claimed": False,
        "advisory_is_not_certification": True,
    }
    (output / "forward_proxy_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certification-dir", required=True)
    parser.add_argument("--current-dir", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--certification-result", required=True)
    parser.add_argument("--current-result", required=True)
    args = parser.parse_args()
    finalize(**vars(args))


if __name__ == "__main__":
    main()
