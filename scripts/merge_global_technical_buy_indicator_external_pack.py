from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.global_technical_buy_indicator import merge_external_strategy_pack_cli


def main() -> int:
    return merge_external_strategy_pack_cli()


if __name__ == "__main__":
    sys.exit(main())
