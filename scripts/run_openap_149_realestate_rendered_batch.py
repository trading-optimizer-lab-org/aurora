from __future__ import annotations

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 rendered realestate sector batch"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
