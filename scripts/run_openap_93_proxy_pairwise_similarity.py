"""GitHub-only pairwise similarity analysis for reconstructed OpenAP proxies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.core.execution_policy import require_github_execution  # noqa: E402
from aurora.research.openap_93.historical_proxy_validation import (  # noqa: E402
    FIVE_PROXY_SIGNALS,
    compare_proxy_pairs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-pairs", type=int, default=30)
    args = parser.parse_args()
    require_github_execution("OpenAP five-proxy pairwise similarity")
    panel = pd.read_parquet(args.panel)
    monthly, summary = compare_proxy_pairs(panel, min_pairs=args.min_pairs)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(output / "proxy_pairwise_similarity_monthly.csv", index=False)
    summary.to_csv(output / "proxy_pairwise_similarity_summary.csv", index=False)
    audit = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "source_panel": str(args.panel),
        "min_pairs": args.min_pairs,
        "official_openap_crosswalk_used": False,
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "lookahead_checked": True,
        "interpretation": "pairwise similarity among reconstructed proxies; not proxy-versus-OpenAP validation",
    }
    (output / "proxy_pairwise_similarity_audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
