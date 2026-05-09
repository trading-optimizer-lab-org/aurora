"""Sphinx configuration for QuantForge API reference (R15)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Path setup
# --------------------------------------------------------------------------

# Repo root is one level above docs/. Adding it to sys.path lets autodoc
# resolve `import aurora` without requiring an editable install on the
# build machine.
_DOCS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))


# --------------------------------------------------------------------------
# Project metadata
# --------------------------------------------------------------------------

project = "QuantForge"
author = "QuantForge Project"
copyright = f"{datetime.now().year}, {author}"

try:
    from aurora import __version__ as _qf_version
except Exception:  # pragma: no cover - import diagnostics
    _qf_version = "0.0.0+unknown"

version = _qf_version
release = _qf_version


# --------------------------------------------------------------------------
# Extensions
# --------------------------------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

autosummary_generate = True
autodoc_default_options = {
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}

# Skip private internals and known-noisy modules from import sweeps.
autodoc_mock_imports = [
    "torch",
    "stable_baselines3",
    "gymnasium",
    "ccxt",
    "alpaca",
    "ib_insync",
    "lumibot",
    "coinbase",
    "krakenex",
    "weasyprint",
    "streamlit",
    "hmmlearn",
    "deap",
    "skopt",
    "joblib",
    "anthropic",
    "cvxpy",
]

# Bring submodules with optional deps into autodoc mock space too -- some
# modules (e.g. aurora.regime.hmm) only attribute-bind when their
# extras are installed, which makes autosummary attribute access fail.
import importlib  # noqa: E402

for _mod in (
    "aurora.regime",
    "aurora.ml",
    "aurora.deployment",
    "aurora.research",
    "aurora.monitoring",
):
    try:
        importlib.import_module(_mod)
    except Exception:  # pragma: no cover - import diagnostics
        pass

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
}

# --------------------------------------------------------------------------
# HTML output
# --------------------------------------------------------------------------

html_theme = "furo"
html_title = f"QuantForge {release}"
html_static_path: list[str] = []
html_show_sourcelink = False
templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "archive",
    "roadmap",
    "DEVELOPMENT_PLAN*.md",
    "GITHUB_RESEARCH*.md",
    "v1_*.md",
    "v2_*.md",
    "v3_*.md",
    "v4_*.md",
]

# Default to short refs in cross-references.
default_role = "py:obj"

# Suppress noisy warnings during broad API sweeps. R20 tracks docstring cleanup
# so these can later be removed and docs can run with -W fully strict.
suppress_warnings = [
    "autodoc.import_object",
    "docutils",
    "myst.xref_missing",
    "toc.not_included",
]

# --------------------------------------------------------------------------
# Build hooks
# --------------------------------------------------------------------------


def setup(app):  # pragma: no cover - sphinx hook
    """Sphinx setup hook reserved for future custom directives."""
    return {
        "version": release,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
