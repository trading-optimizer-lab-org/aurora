"""Worktree-root conftest: ensure this checkout's aurora package wins over
any editable install pointing elsewhere.

Background
----------
The Aurora editable install records its location in
``__editable___aurora_1_5_0_finder.py`` under site-packages. When multiple
checkouts (the main repo + git worktrees) coexist on disk and either runs
``pip install -e .``, that finder is rewritten to whichever path was
installed last. Tests run from this worktree must use *this* checkout's
source — not whichever path happened to win the last install race.

Strategy: rewrite the editable finder's MAPPING at conftest import time so
``aurora`` resolves to *this* worktree, regardless of which checkout last
ran ``pip install -e .``. Any aurora modules already loaded are evicted
from ``sys.modules`` so subsequent imports go through the corrected path.
"""
from __future__ import annotations

import sys
from pathlib import Path

_WORKTREE = Path(__file__).resolve().parent
_PATH = str(_WORKTREE)

try:
    import __editable___aurora_1_5_0_finder as _finder
    _finder.MAPPING['aurora'] = _PATH
    # Pytest can import this file either as ``conftest`` or as
    # ``aurora.conftest``. Evicting the parent package while the latter is
    # still importing causes importlib to fail with KeyError. Only the
    # top-level form is safe to repair in place; CI's editable install already
    # points at the active checkout for the package-qualified form.
    if __name__ == "conftest":
        for _name in list(sys.modules):
            if _name == "aurora" or _name.startswith("aurora."):
                del sys.modules[_name]
except ImportError:
    # Editable finder not present (e.g. running from a wheel install). Fall
    # back to plain sys.path injection — harmless if aurora is already
    # importable via a different mechanism.
    if _PATH not in sys.path:
        sys.path.insert(0, _PATH)
