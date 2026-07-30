from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.execution_policy import require_github_only_execution


def main() -> int:
    require_github_only_execution("external GTBI strategy-pack shard")
    from scripts.global_technical_buy_indicator import run_external_strategy_pack_shard_cli

    return run_external_strategy_pack_shard_cli()


if __name__ == "__main__":
    sys.exit(main())
