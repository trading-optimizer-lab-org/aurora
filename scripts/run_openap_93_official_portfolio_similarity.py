from __future__ import annotations

import argparse

from research.openap_93.official_portfolio_similarity import run_official_portfolio_similarity


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare five Aurora proxies with official OpenAP decile portfolios")
    parser.add_argument("--proxy-panel", required=True)
    parser.add_argument("--monthly", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--release", default="202510")
    args = parser.parse_args()
    run_official_portfolio_similarity(
        proxy_panel=args.proxy_panel,
        monthly=args.monthly,
        output_dir=args.output_dir,
        release=args.release,
    )


if __name__ == "__main__":
    main()
