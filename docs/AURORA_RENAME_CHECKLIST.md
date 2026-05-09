# Aurora Rename Execution Checklist (R23)

## Status

**Executed 2026-05-09 (commit `cf41bc2`).** `pyproject.toml`
`name = "aurora"`; package-dir map re-routes `aurora.*` to the
on-disk dirs; CLI entry `aurora`; `forge` kept as deprecated alias.
`quantforge/__init__.py` shim re-exports aurora and emits
`DeprecationWarning`. `core/env_compat.py::aurora_env(new, old)`
reads `AU_*` first, falls back to `QF_*` with `DeprecationWarning`.

Wheel builds as `aurora-1.5.0-py3-none-any.whl`. Both `import aurora`
(no warning) and `import quantforge` (DeprecationWarning) work.
`aurora --version` -> `aurora 1.5.0`.

The text below is the original checklist, kept for historical
reference and as the playbook the next major-version rename should
follow. The shim is removed in v1.6 per the deprecation timeline in
`docs/ENV_VAR_MIGRATION_PLAN.md`.

## Why the rename is its own track

The rename touches every file that references the project name. Done
in pieces, half-renames stay in main and confuse downstream consumers.
Done in a bundled PR, the rename collides with semantic work and
review takes weeks.

The right shape: one rename branch, one merge, one shim release.

## Pre-flight checks (must pass before starting)

- [x] R7 / R19 closed (snapshot backend abstraction is real, not just
      planned). Already done in batches 1 + 16.
- [x] R16 zero-MDD Calmar contract closed.
- [x] `ruff check .` clean. Already verified.
- [x] Full fast suite green (3010 tests + 161 batch tests).
- [x] R76 env var migration plan locked
      (`docs/ENV_VAR_MIGRATION_PLAN.md`).
- [ ] Branch `aurora-rename` cut from main; rebase before each step.

## Execution steps

### 1. Repo top-level rename

```bash
# from outside the repo dir
git mv QuantForge Aurora
```

`pyproject.toml` `[tool.setuptools]` `package-dir` map updates so the
on-disk package directory still resolves to the `aurora` import path.

### 2. Package import path migration

Sed-style rename across the tree, scoped to Python source only:

```bash
# Rough shape; do NOT run blindly. Operator runs in a branch and
# reviews the diff on each module before committing.
find . -name '*.py' \
    -not -path './build/*' \
    -not -path './.venv/*' \
    -not -path './.claude/*' \
    -exec sed -i '' \
        -e 's/^import quantforge/import aurora/g' \
        -e 's/^from quantforge\./from aurora./g' \
        -e "s/'quantforge\\./'aurora./g" \
        -e 's/"quantforge\\./"aurora./g' \
        {} +
```

Per-module review: each rename PR commits one directory at a time so
reviewers see a focused diff (`core/`, then `validation/`, then
`ga/`, etc).

### 3. Compatibility shim

Land `aurora/_quantforge_shim.py`:

```python
# pseudo-code shape; lands when the rename branch is ready
import importlib
import warnings


def _install_shim():
    import sys
    import aurora
    sys.modules.setdefault("quantforge", aurora)
    warnings.filterwarnings(
        "default",
        message=r"`quantforge\..*` is deprecated; use `aurora\..*`",
    )
```

Imports of `quantforge.*` resolve via the shim and emit a
`DeprecationWarning`. The shim is removed in v1.6.

### 4. Env var migration

Already specified in `docs/ENV_VAR_MIGRATION_PLAN.md` (R76). Land the
`core/env_compat.py::aurora_env(...)` helper + migrate every reader to
call it.

### 5. CLI entry point

```toml
[project.scripts]
aurora = "aurora.cli.forge:main"
```

The `forge` entry point stays as a deprecated alias for one cycle.

### 6. Documentation

Update every operator-facing doc:

- `CLAUDE.md`
- `README.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `docs/ZERO_TO_LIVE.md`
- `docs/RESEARCH_PROTOCOL.md`
- `docs/SPINE.md` (if present)
- `docs/MODULE_STATUS.md`
- `docs/ENV_VARS.md`
- All `docs/v*_COMPLETION_REPORT.md` and `docs/archive/*` left as
  historical references; do NOT rewrite them.

### 7. Wheel + release

- `python -m build` produces `aurora-1.5.0-py3-none-any.whl`.
- CHANGELOG carries the rename + shim window.
- Release tag `v1.5.0`; the shim is removed in `v1.6.0`.

## Definition of done

- [x] `import aurora` resolves to the rename branch's package.
- [x] `import quantforge` works AND emits a `DeprecationWarning`
      during the shim window.
- [x] `aurora --version` returns the new package version.
- [x] All operator docs reference Aurora consistently.
- [x] Tests green under the new import path (3370 fast suite + 3
      slow/integration).
- [x] Wheel builds as `aurora-X.Y.Z` (`aurora-1.5.0-py3-none-any.whl`).

## Rollback plan

If the rename branch hits a regression in main that cannot be hot-
fixed, revert the merge commit. The rename is fully contained in one
merge so revert is clean. The compat shim makes the revert window
even safer because downstream consumers can keep importing
`quantforge.*` either way.

## Why this checklist is the canonical reference

Future sessions referencing R23 should consult this file plus the
detailed roadmap entry above. Do NOT re-derive the migration shape;
the plan stays stable until the rename branch lands.
