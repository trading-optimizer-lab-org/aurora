"""mutmut configuration for Aurora mutation testing (R12).

mutmut 3.x reads ``[tool.mutmut]`` from ``pyproject.toml`` for
``paths_to_mutate`` and pytest test-selection arguments. This file exists to
document the targets and to provide hooks that mutmut can import.

Usage::

    # Targeted run on the curated core surface (see TARGETS below)
    python -m mutmut run

    # Surviving mutants report
    python -m mutmut results

    # Inspect a single survivor
    python -m mutmut show <id>

The mutation suite uses the *property-based* tests by default because they
exercise invariants (good at killing semantic mutants), plus the focused
unit tests on the same modules.
"""
from __future__ import annotations


# Curated mutation targets.
#
# These are the modules where a successfully-applied mutation is genuinely
# dangerous (silent risk, lost provenance, or wrong PnL accounting).
TARGETS: tuple[str, ...] = (
    "core/engine.py",
    "core/engine_multi.py",
    "core/costs.py",
    "core/metrics.py",
    "core/data_tiers.py",
    "core/data_layer.py",
    "core/protocol_policy.py",
    "validation/walk_forward.py",
    "validation/monte_carlo.py",
    "validation/spp.py",
    "validation/deflated_sharpe.py",
    "validation/lookahead_check.py",
    "validation/pipeline.py",
    "ga/fitness.py",
)


# Paths excluded entirely. mutmut should not touch these.
EXCLUDE: tuple[str, ...] = (
    "tests/",
    "docs/",
    "examples/",
    "experimental/",
    "build/",
    "*/__pycache__/*",
    "*.pyc",
)


def pre_mutation(context):  # pragma: no cover - mutmut hook
    """mutmut hook: skip mutations on lines marked ``# no-mutate``.

    Useful for lines that are correct by definition (e.g. a hash seed
    constant) where any mutation creates a misleading "survivor".
    """
    if "# no-mutate" in context.current_source_line:
        context.skip = True
