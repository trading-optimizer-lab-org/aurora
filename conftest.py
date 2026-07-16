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
    # Evict only modules that actually came from another checkout. Removing
    # the active package itself breaks pytest's import bookkeeping.
    for _name, _module in list(sys.modules.items()):
        if _name == __name__ or not (_name == 'aurora' or _name.startswith('aurora.')):
            continue
        _file = getattr(_module, '__file__', None)
        if _file is None:
            continue
        try:
            Path(_file).resolve().relative_to(_WORKTREE)
        except ValueError:
            del sys.modules[_name]
except ImportError:
    # Editable finder not present (e.g. running from a wheel install). Fall
    # back to plain sys.path injection — harmless if aurora is already
    # importable via a different mechanism.
    if _PATH not in sys.path:
        sys.path.insert(0, _PATH)
