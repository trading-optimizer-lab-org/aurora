from __future__ import annotations

import sys

from scripts.global_technical_buy_indicator import merge_external_strategy_pack_cli


def main() -> int:
    return merge_external_strategy_pack_cli()


if __name__ == "__main__":
    sys.exit(main())
