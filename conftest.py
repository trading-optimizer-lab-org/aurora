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
    _aurora = sys.modules.get("aurora")
    if _aurora is not None:
        # Pytest may import this file as ``aurora.conftest`` after another
        # checkout's editable install has already loaded the parent package.
        # Keep the parent object alive while its conftest is importing, but
        # redirect its package search path and evict stale children. Future
        # imports then resolve exclusively from this worktree.
        _aurora.__path__ = [_PATH]
        _aurora.__file__ = str(_WORKTREE / "__init__.py")
        _current_conftest = __name__ if __name__.startswith("aurora.") else None
        for _name, _module in list(sys.modules.items()):
            if not _name.startswith("aurora.") or _name == _current_conftest:
                continue
            _module_file = getattr(_module, "__file__", None)
            if _module_file is None:
                continue
            try:
                _module_path = Path(_module_file).resolve()
                _module_path.relative_to(_WORKTREE)
            except (OSError, ValueError):
                del sys.modules[_name]
except ImportError:
    # Editable finder not present (e.g. running from a wheel install). Fall
    # back to plain sys.path injection — harmless if aurora is already
    # importable via a different mechanism.
    if _PATH not in sys.path:
        sys.path.insert(0, _PATH)
