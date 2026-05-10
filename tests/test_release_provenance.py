"""Release provenance + compatibility hardening tests (R188).

Covers:

- ``aurora.__version__`` agrees with ``pyproject.toml``'s ``project.version``.
- ``import quantforge`` emits a ``DeprecationWarning`` (shim contract).
- ``QF_*`` env vars route through ``aurora.core.env_compat.aurora_env`` and
  emit a ``DeprecationWarning``.
- ``docs/RELEASE_CHECKLIST.md`` exists and references the wheel-smoke step
  plus the deferred public signing decision.
- ``tools/release_smoke.py`` is a syntactically valid Python file.

These are intentionally cheap. The actual wheel-smoke step is run via
``python tools/release_smoke.py`` -- it is NOT invoked from any test
because a real wheel build is too slow.
"""
from __future__ import annotations

import ast
import importlib
import sys
import tomllib
import warnings
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_pyproject_version() -> str:
    """Pull ``project.version`` straight from ``pyproject.toml``."""
    pyproject = REPO_ROOT / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    return data["project"]["version"]


def test_aurora_version_matches_pyproject() -> None:
    """``aurora.__version__`` must agree with ``pyproject.toml``'s version."""
    import aurora

    expected = _read_pyproject_version()
    # The source-checkout fallback is ``"0.0.0+local"`` (PEP 440 local version
    # marker). If the package is installed normally, importlib.metadata returns
    # the wheel version. Either way, an installed Aurora must match pyproject.
    assert aurora.__version__ in (
        expected,
        "0.0.0+local",
    ), (
        f"aurora.__version__={aurora.__version__!r} does not match "
        f"pyproject.toml version={expected!r}"
    )


def test_quantforge_shim_emits_deprecation_warning() -> None:
    """Importing the ``quantforge`` compat shim must emit a DeprecationWarning.

    The shim fires its warning at module-import time. Because Python caches
    modules in ``sys.modules`` and dedups warnings by (location, message),
    we drop any cached ``quantforge*`` module entries first and then force a
    fresh import inside a ``catch_warnings`` block with ``always`` filter.
    """
    # Wipe any cached quantforge modules so the import statement re-executes
    # the shim's top-level ``warnings.warn(...)`` call.
    for mod_name in list(sys.modules):
        if mod_name == "quantforge" or mod_name.startswith("quantforge."):
            del sys.modules[mod_name]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("quantforge")

    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecations, (
        "import quantforge did not emit a DeprecationWarning; "
        "shim contract is broken (see quantforge/__init__.py)."
    )
    # The shim's warning text references the v1.6 retirement.
    messages = " ".join(str(w.message) for w in deprecations)
    assert "quantforge" in messages.lower()
    assert "aurora" in messages.lower()


def test_qf_env_var_emits_deprecation_warning(monkeypatch) -> None:
    """``aurora_env(...)`` must warn when the legacy ``QF_*`` name is used."""
    from aurora.core.env_compat import aurora_env

    # Make sure the new name is NOT set, force the legacy fallback path.
    monkeypatch.delenv("AU_FAKE_R188", raising=False)
    monkeypatch.setenv("QF_FAKE_R188", "legacy-value")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        value = aurora_env("AU_FAKE_R188", "QF_FAKE_R188", default=None)

    assert value == "legacy-value"
    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecations, (
        "aurora_env did not warn when only the legacy QF_* var was set."
    )
    msg = str(deprecations[0].message)
    assert "QF_FAKE_R188" in msg
    assert "AU_FAKE_R188" in msg


def test_qf_env_var_no_warning_when_new_name_set(monkeypatch) -> None:
    """When the canonical ``AU_*`` name is set, no warning fires."""
    from aurora.core.env_compat import aurora_env

    monkeypatch.setenv("AU_FAKE_R188", "new-value")
    monkeypatch.setenv("QF_FAKE_R188", "legacy-value")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        value = aurora_env("AU_FAKE_R188", "QF_FAKE_R188", default=None)

    assert value == "new-value"
    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert not deprecations, (
        "aurora_env emitted a deprecation warning even though the "
        "canonical AU_* name was set."
    )


def test_release_checklist_exists_and_covers_required_topics() -> None:
    """The release checklist doc must exist and cover the R188 acceptance items."""
    checklist = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"
    assert checklist.exists(), (
        f"Release checklist missing at {checklist}. R188 requires it."
    )
    text = checklist.read_text(encoding="utf-8").lower()
    # Wheel smoke section is mandatory.
    assert "wheel smoke" in text or "release_smoke" in text
    # Public signing is documented as deferred / optional.
    assert "sigstore" in text or "trusted publishing" in text
    # Shim retirement target points at v1.6.
    assert "v1.6" in text
    assert "quantforge" in text


def test_release_smoke_script_is_syntactically_valid() -> None:
    """``tools/release_smoke.py`` must parse with ``ast.parse``."""
    script = REPO_ROOT / "tools" / "release_smoke.py"
    assert script.exists(), f"release_smoke.py missing at {script}"
    source = script.read_text(encoding="utf-8")
    # If the script has a syntax error, ast.parse raises and the test fails.
    ast.parse(source, filename=str(script))


def test_release_smoke_script_defines_main() -> None:
    """The smoke script must expose a ``main()`` callable for manual runs."""
    script = REPO_ROOT / "tools" / "release_smoke.py"
    source = script.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script))
    main_funcs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert main_funcs, "tools/release_smoke.py must define a top-level main()."


# Sanity: pytest auto-discovery should match this file via the default
# ``test_*.py`` pattern; no extra config needed.
if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q", "--tb=short"]))
