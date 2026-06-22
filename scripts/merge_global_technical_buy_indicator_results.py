from __future__ import annotations

from core.execution_policy import require_github_actions_or_explicit_local_permission
from scripts.global_technical_buy_indicator import merge_cli


def main() -> int:
    require_github_actions_or_explicit_local_permission("global technical buy indicator merge")
    return merge_cli()


if __name__ == "__main__":
    raise SystemExit(main())
