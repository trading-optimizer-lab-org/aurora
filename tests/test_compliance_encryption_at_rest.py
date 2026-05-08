"""Tests for quantforge.compliance.encryption_at_rest."""
from __future__ import annotations

import pytest

from quantforge.compliance.encryption_at_rest import (
    SQLCipherConfig,
    SQLCipherWrapper,
)


@pytest.fixture
def wrapper(tmp_path) -> SQLCipherWrapper:
    cfg = SQLCipherConfig(db_path=str(tmp_path / "enc.sqlite"))
    return SQLCipherWrapper(cfg)


def test_is_available_returns_bool(wrapper):
    assert isinstance(wrapper.is_available(), bool)


def test_connect_without_key_raises(wrapper, monkeypatch):
    monkeypatch.delenv("QF_SQLCIPHER_KEY", raising=False)
    if not wrapper.is_available():
        with pytest.raises(ImportError):
            wrapper.connect()
    else:  # pragma: no cover - requires C extension
        with pytest.raises(RuntimeError, match="QF_SQLCIPHER_KEY"):
            wrapper.connect()


def test_connect_without_driver_raises_import_error(wrapper, monkeypatch):
    monkeypatch.setenv("QF_SQLCIPHER_KEY", "test-passphrase")
    if not wrapper.is_available():
        with pytest.raises(ImportError):
            wrapper.connect()


def test_escape_pragma_rejects_quotes():
    with pytest.raises(ValueError):
        SQLCipherWrapper._escape_pragma("evil'; --")
    with pytest.raises(ValueError):
        SQLCipherWrapper._escape_pragma('also"evil')


def test_escape_pragma_passes_clean_value():
    val = SQLCipherWrapper._escape_pragma("clean-passphrase-1234")
    assert val == "clean-passphrase-1234"


def test_default_config_is_secure_enough():
    cfg = SQLCipherConfig()
    assert cfg.kdf_iter >= 100000
    assert cfg.cipher_page_size in (1024, 4096, 8192, 16384, 32768, 65536)


def test_custom_db_path_used(tmp_path):
    cfg = SQLCipherConfig(db_path=str(tmp_path / "custom.db"))
    w = SQLCipherWrapper(cfg)
    assert w.config.db_path.endswith("custom.db")
