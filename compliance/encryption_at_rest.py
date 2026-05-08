"""Optional sqlcipher wrapper for encrypted SQLite at rest.

Wraps ``pysqlcipher3`` (or the ``sqlcipher3`` fork) with a thin connection
helper. The driver is imported lazily so the module remains importable
without sqlcipher installed.

When the driver is unavailable, ``connect()`` raises a clear ImportError
with installation hints. The configured key is read from an environment
variable; never hardcode keys.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class SQLCipherConfig:
    """Static config for the SQLCipher wrapper.

    Attributes:
        db_path: path to the encrypted SQLite database file.
        key_env: env var holding the SQLCipher key (passphrase or hex blob key).
        kdf_iter: number of PBKDF2 iterations. Default matches sqlcipher 4.
        cipher_page_size: page size in bytes (4096 is the sqlcipher 4 default).
    """
    db_path: str = "encrypted.sqlite"
    key_env: str = "QF_SQLCIPHER_KEY"
    kdf_iter: int = 256000
    cipher_page_size: int = 4096
    extra_pragmas: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class SQLCipherWrapper:
    """Lazy sqlcipher connection helper."""

    def __init__(self, config: Optional[SQLCipherConfig] = None) -> None:
        self.config = config or SQLCipherConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if a sqlcipher driver is importable."""
        return self._import_driver() is not None

    def connect(self) -> Any:
        """Open and return an authenticated sqlcipher connection.

        Raises:
            ImportError: if no sqlcipher driver is installed.
            RuntimeError: if the configured key env var is missing.
        """
        driver = self._import_driver()
        if driver is None:
            raise ImportError(
                "no sqlcipher driver found. Install pysqlcipher3 or sqlcipher3"
            )
        key = os.environ.get(self.config.key_env, "")
        if not key:
            raise RuntimeError(
                f"missing env var {self.config.key_env}; refusing to open db"
            )
        path = Path(self.config.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = driver.connect(str(path))  # pragma: no cover - needs C ext
        cur = conn.cursor()  # pragma: no cover - needs C ext
        cur.execute(f"PRAGMA key = '{self._escape_pragma(key)}'")  # pragma: no cover
        cur.execute(f"PRAGMA kdf_iter = {int(self.config.kdf_iter)}")  # pragma: no cover
        cur.execute(  # pragma: no cover
            f"PRAGMA cipher_page_size = {int(self.config.cipher_page_size)}"
        )
        for name, val in self.config.extra_pragmas:  # pragma: no cover
            cur.execute(f"PRAGMA {name} = {val}")
        return conn  # pragma: no cover

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _import_driver() -> Optional[Any]:
        try:
            import pysqlcipher3.dbapi2 as driver  # type: ignore
            return driver
        except ImportError:
            pass
        try:
            import sqlcipher3 as driver  # type: ignore
            return driver
        except ImportError:
            return None

    @staticmethod
    def _escape_pragma(value: str) -> str:
        # SQLCipher PRAGMA values cannot use parameter binding; reject quotes
        # to avoid trivial injection.
        if "'" in value or "\"" in value:
            raise ValueError("sqlcipher key must not contain quote characters")
        return value
