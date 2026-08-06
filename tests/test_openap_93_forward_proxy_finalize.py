from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.finalize_openap_five_forward_proxies import finalize


def test_finalizer_keeps_only_certified_current_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    certification = tmp_path / "certification"
    current = tmp_path / "current"
    output = tmp_path / "final"
    certification.mkdir()
    current.mkdir()
    pd.DataFrame(
        [
            {
                "signal": "DivSeason",
                "variant_id": "v1",
                "common_months": 120,
                "pearson": 0.9,
                "spearman": 0.91,
                "sign_agreement": 0.8,
                "passed": True,
            }
        ]
    ).to_csv(certification / "forward_proxy_validation_metrics.csv", index=False)
    pd.DataFrame([{"signal": "DivSeason", "variant_id": "v1"}]).to_csv(
        certification / "forward_proxy_candidate_metrics.csv", index=False
    )
    (certification / "forward_proxy_certificates.jsonl").write_text(
        json.dumps({"signal": "DivSeason"}) + "\n", encoding="utf-8"
    )
    pd.DataFrame(
        [
            {
                "ticker": "A",
                "signal": "DivSeason",
                "value": 1.0,
                "current_usable": True,
                "certificate_status": "certified",
            },
            {
                "ticker": "B",
                "signal": "DelNetFin",
                "value": 0.1,
                "current_usable": False,
                "certificate_status": "missing_certificate",
            },
        ]
    ).to_csv(current / "signals_93_current.csv", index=False)
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(
        "signals:\n"
        "  DivSeason:\n"
        "    formula_id: v1\n"
        "    accepted_variants: [v1]\n"
        "    sources: [public]\n"
        "    code: [formula.py]\n",
        encoding="utf-8",
    )

    summary = finalize(
        certification_dir=certification,
        current_dir=current,
        source_manifest=manifest,
        output_dir=output,
        certification_result="success",
        current_result="success",
    )

    score_ready = pd.read_csv(output / "forward_proxy_score_ready.csv")
    assert score_ready[["ticker", "signal"]].to_dict(orient="records") == [
        {"ticker": "A", "signal": "DivSeason"}
    ]
    assert summary["signals_certified"] == 1
    assert summary["score_ready_rows"] == 1
    assert summary["partial"] is False
    assert summary["locked_opened"] is False
