# ADR 0005: Aurora Repository Layout After GTBI V7

## Decision

Aurora retains its current flat Python package layout. A repository-wide move
would add risk without improving the completed V7 result.

- Reusable library code remains in top-level package directories.
- GTBI execution entry points remain thin files under `scripts/`.
- GitHub workflows remain directly under `.github/workflows/`.
- Frozen scientific contracts live under `config/gtbi/`.
- Readiness evidence lives under `docs/readiness/`.
- Inventory tables live under `docs/project_inventory/`.
- Historical workflow material may move only to `docs/archive/workflows/` after
  an exact inventory and explicit approval.
- Runtime data and artifacts never enter the repository and use runtime paths
  or immutable GitHub release assets.

## Modernization policy

Non-GTBI modernization is staged and opportunistic: packaging metadata,
imports and tests may be cleaned when touched, but broad rewrites are not a V7
completion dependency. Existing public interfaces remain compatible.

## Status

Accepted. No destructive repository move is authorized by this ADR.
