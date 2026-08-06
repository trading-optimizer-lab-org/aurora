from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.research.openap_93.official_portfolio_similarity import (  # noqa: E402
    run_official_portfolio_similarity,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare five Aurora proxies with official OpenAP decile portfolios")
    parser.add_argument("--proxy-panel", required=True)
    parser.add_argument("--monthly", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--release", default="202510")
    parser.add_argument("--official-deciles", default="")
    parser.add_argument("--official-long-short", default="")
    args = parser.parse_args()
    run_official_portfolio_similarity(
        proxy_panel=args.proxy_panel,
        monthly=args.monthly,
        output_dir=args.output_dir,
        release=args.release,
        official_deciles=args.official_deciles or None,
        official_long_short=args.official_long_short or None,
    )


if __name__ == "__main__":
    main()
