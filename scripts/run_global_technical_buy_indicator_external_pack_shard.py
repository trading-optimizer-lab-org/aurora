from __future__ import annotations

import os
import sys


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") != "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
        raise SystemExit(
            "External GTBI shard runs are GitHub-only. Set AURORA_ALLOW_LOCAL_RUNS_EXPLICIT=USER_REQUESTED_LOCAL_RUN_THIS_TURN "
            "only for tiny local smoke tests explicitly requested in the current turn."
        )
    from scripts.global_technical_buy_indicator import run_external_strategy_pack_shard_cli

    return run_external_strategy_pack_shard_cli()


if __name__ == "__main__":
    sys.exit(main())
