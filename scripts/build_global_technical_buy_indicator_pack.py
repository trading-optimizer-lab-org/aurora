from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.global_technical_buy_indicator import build_pack_cli


def require_github_actions_or_explicit_local_permission(run_kind: str) -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return
    if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
        return
    raise RuntimeError(
        "Run local bloqueado por politica Aurora. "
        f"Lanzalo en GitHub Actions o pide explicitamente ejecucion local. Tipo: {run_kind}."
    )


def main() -> int:
    require_github_actions_or_explicit_local_permission("global technical buy indicator pack build")
    return build_pack_cli()


if __name__ == "__main__":
    raise SystemExit(main())
