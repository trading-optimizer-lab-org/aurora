from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.global_technical_buy_indicator import run_stage_cli
from core.execution_policy import require_github_only_execution


def main() -> int:
    require_github_only_execution("global technical buy indicator stage")
    return run_stage_cli()


if __name__ == "__main__":
    raise SystemExit(main())
