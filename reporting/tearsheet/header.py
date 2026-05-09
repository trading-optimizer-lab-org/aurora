"""Hero / preamble helpers: HTML escape, matplotlib backend management,
figure -> base64 PNG, and DatetimeIndex coercion.

These primitives are imported by every other tearsheet section.
"""
from __future__ import annotations

import base64
import contextlib
import html as _html
import io
import os

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _esc(value) -> str:
    """HTML-escape an arbitrary value for safe interpolation into the
    template. ``None`` / NaN render as ``""``.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return "NaN"
        return _html.escape(repr(value), quote=True)
    return _html.escape(str(value), quote=True)


_BACKEND_FORCED = False


def _ensure_agg_backend():
    """Force Agg backend lazily. Idempotent. Always safe in headless / CI.

    On non-Windows hosts we previously gated on $DISPLAY, but matplotlib's Tk
    backend can fail on minimal Windows installs (no Tk runtime), so we now
    use Agg whenever no GUI display is available. Existing interactive
    sessions with DISPLAY set or running inside an IDE keep their backend.

    NOTE: this performs a *global* backend switch and is reserved for the
    one-shot import-time fallback below. From inside test code, prefer
    :func:`agg_backend_scope`, which restores the prior backend on exit so
    a unit test for tearsheet rendering does not leak backend state into
    sibling tests that assume the user-configured GUI backend.
    """
    global _BACKEND_FORCED
    if _BACKEND_FORCED:
        return
    has_display = (
        os.environ.get("DISPLAY")
        or os.environ.get("MPLBACKEND")
        or os.environ.get("PYCHARM_HOSTED")
    )
    if not has_display:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass
    _BACKEND_FORCED = True


@contextlib.contextmanager
def agg_backend_scope():
    """Context manager that ensures Agg is the active matplotlib backend
    inside the ``with`` block and restores the prior backend on exit.

    Used by the public render helpers when called under pytest
    (``PYTEST_CURRENT_TEST`` set in env): tearsheet rendering must always
    succeed without a GUI display, but the test should not leak a global
    backend change into other tests.

    Outside a test environment this still works correctly — it just acts
    as a transient switch into Agg with restoration on exit.

    The module-level ``_BACKEND_FORCED`` flag is also reset on exit so
    that a subsequent non-pytest call to :func:`_ensure_agg_backend` will
    re-evaluate display state instead of skipping based on a stale
    "already forced" state from inside the scope.
    """
    global _BACKEND_FORCED
    prior_forced = _BACKEND_FORCED
    prior = matplotlib.get_backend()
    switched = False
    if prior.lower() != "agg":
        try:
            matplotlib.use("Agg", force=True)
            switched = True
        except Exception:
            switched = False
    try:
        yield
    finally:
        if switched:
            try:
                matplotlib.use(prior, force=True)
            except Exception:
                # If we cannot restore (e.g. Tk no longer available in this
                # process), leave Agg active rather than crashing — the
                # original backend was probably non-functional anyway.
                pass
        # Restore the prior ``_BACKEND_FORCED`` value so the lazy switch
        # path can fire again if the surrounding session expects it.
        _BACKEND_FORCED = prior_forced


def _running_under_pytest() -> bool:
    """True iff the current process is executing inside a pytest test.

    Triggered by pytest's per-test ``PYTEST_CURRENT_TEST`` env var, which is
    set even for parameterized and concurrent runs.
    """
    return "PYTEST_CURRENT_TEST" in os.environ


# Force Agg at import time too: many code paths call plt.subplots before the
# first _fig_to_base64 (which is where the lazy switch used to fire), so the
# Tk default backend would be picked up first and fail on Tk-less environments.
# Under pytest we instead defer the switch to render time via
# ``agg_backend_scope`` so tests do not leak a global backend change.
if not _running_under_pytest():
    _ensure_agg_backend()


def _to_pd_index(timestamps) -> pd.DatetimeIndex:
    """Convert np.datetime64 array (or anything pandas can parse) to DatetimeIndex."""
    return pd.DatetimeIndex(pd.to_datetime(timestamps))


def _fig_to_base64(fig) -> str:
    """Render matplotlib Figure to base64-encoded PNG string."""
    _ensure_agg_backend()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
