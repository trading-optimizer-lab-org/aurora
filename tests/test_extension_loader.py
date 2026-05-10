"""R186 - Tests for the extension loader / discovery / registration.

Uses the in-tree examples under ``examples/extensions/`` after pointing
``AU_EXTENSION_DIRS`` at that directory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aurora.core.data_providers import (
    DataProviderRegistry,
    Dataset,
    get_default_registry,
    reset_default_registry,
)
from aurora.core.extension_api import IncompatibleInterfaceError
from aurora.core.extension_loader import (
    EXTENSION_FILE_SUFFIX,
    ExtensionLoadError,
    LoadedExtension,
    discover_extensions,
    load_extension,
    register_loaded_extensions,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_DIR = _REPO_ROOT / "examples" / "extensions"


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each loader test starts with a fresh DataProviderRegistry."""
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture
def example_provider_path() -> Path:
    p = _EXAMPLES_DIR / f"example_provider{EXTENSION_FILE_SUFFIX}"
    assert p.exists(), p
    return p


@pytest.fixture
def example_strategy_path() -> Path:
    p = _EXAMPLES_DIR / f"example_strategy{EXTENSION_FILE_SUFFIX}"
    assert p.exists(), p
    return p


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_example_provider_loads(monkeypatch, example_provider_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    ext = load_extension(example_provider_path)
    assert isinstance(ext, LoadedExtension)
    assert ext.kind == "DataProvider"
    assert ext.name == "example_ext_provider"
    assert ext.interface_version == "1.0.0"
    instance = ext.factory()
    assert instance.is_point_in_time() is True


def test_example_strategy_loads(monkeypatch, example_strategy_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    ext = load_extension(example_strategy_path)
    assert ext.kind == "Strategy"
    assert ext.name == "example_ext_strategy"
    cls = ext.factory()
    assert isinstance(cls, type)


def test_discover_finds_both_examples(monkeypatch):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    found = discover_extensions()
    names = {ext.name for ext in found}
    assert {"example_ext_provider", "example_ext_strategy"}.issubset(names)


# ---------------------------------------------------------------------------
# Failure paths register nothing
# ---------------------------------------------------------------------------


_BAD_EXT_BODY = """
__aurora_extension__ = {
    'name': 'bad',
    'kind': 'DataProvider',
    # missing interface_version on purpose
    'factory': lambda: None,
    'capabilities': {},
}
"""


def test_loader_writes_nothing_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(tmp_path))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    p = tmp_path / f"bad{EXTENSION_FILE_SUFFIX}"
    p.write_text(_BAD_EXT_BODY, encoding="utf-8")
    with pytest.raises((ExtensionLoadError, IncompatibleInterfaceError)):
        load_extension(p)
    # Registry must be untouched.
    registry = get_default_registry()
    assert "bad" not in registry.list()


# ---------------------------------------------------------------------------
# Registration round-trip
# ---------------------------------------------------------------------------


def test_register_data_provider_round_trips(
    monkeypatch, example_provider_path
):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    ext = load_extension(example_provider_path)
    summary = register_loaded_extensions([ext])
    assert summary == {"DataProvider": ["example_ext_provider"]}

    registry = get_default_registry()
    assert "example_ext_provider" in registry.list()
    provider = registry.get("example_ext_provider")
    ds = provider.fetch("FOO", None, None)
    assert isinstance(ds, Dataset)
    assert ds.metadata.point_in_time is True


def test_register_refuses_duplicate_without_replace(
    monkeypatch, example_provider_path
):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    ext = load_extension(example_provider_path)
    register_loaded_extensions([ext])
    with pytest.raises(ValueError):
        register_loaded_extensions([ext])


def test_register_replace_overwrites(monkeypatch, example_provider_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(_EXAMPLES_DIR))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    ext = load_extension(example_provider_path)
    register_loaded_extensions([ext])
    # Second registration with replace=True must succeed.
    summary = register_loaded_extensions([ext], replace=True)
    assert summary == {"DataProvider": ["example_ext_provider"]}
