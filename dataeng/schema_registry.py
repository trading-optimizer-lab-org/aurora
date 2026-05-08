"""Versioned schema registry backed by SQLite.

Stores Avro/JSONSchema documents under ``(subject, version)`` keys. New
versions are inserted monotonically per subject. Validation only checks the
shape of the document, not full Avro semantics; deeper validation can be
plugged in lazily by the caller.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SchemaRegistryConfig:
    """Static config for :class:`SchemaRegistry`.

    Attributes:
        db_path: SQLite path. ``:memory:`` for ephemeral.
        format: ``avro`` or ``jsonschema``.
    """
    db_path: str = ":memory:"
    format: str = "jsonschema"


@dataclass
class SchemaVersion:
    subject: str
    version: int
    schema: dict
    format: str
    created_at: float


_DDL = (
    "CREATE TABLE IF NOT EXISTS schemas ("
    " subject TEXT NOT NULL,"
    " version INTEGER NOT NULL,"
    " schema_json TEXT NOT NULL,"
    " format TEXT NOT NULL,"
    " created_at REAL NOT NULL,"
    " PRIMARY KEY (subject, version)"
    ")"
)


class SchemaRegistry:
    """Versioned schema store with SQLite backing."""

    def __init__(self, config: Optional[SchemaRegistryConfig] = None) -> None:
        self.config = config or SchemaRegistryConfig()
        self._conn = sqlite3.connect(self.config.db_path)
        self._conn.execute(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    def register(self, subject: str, schema: dict) -> SchemaVersion:
        if not isinstance(schema, dict) or not schema:
            raise ValueError("schema must be a non-empty dict")
        cur = self._conn.execute(
            "SELECT MAX(version) FROM schemas WHERE subject = ?", (subject,))
        row = cur.fetchone()
        next_version = int((row[0] or 0)) + 1
        now = time.time()
        self._conn.execute(
            "INSERT INTO schemas(subject, version, schema_json, format,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (subject, next_version, json.dumps(schema, sort_keys=True),
             self.config.format, now),
        )
        self._conn.commit()
        return SchemaVersion(subject=subject, version=next_version,
                             schema=dict(schema), format=self.config.format,
                             created_at=now)

    def get(self, subject: str,
            version: Optional[int] = None) -> Optional[SchemaVersion]:
        if version is None:
            return self.latest(subject)
        cur = self._conn.execute(
            "SELECT subject, version, schema_json, format, created_at "
            "FROM schemas WHERE subject = ? AND version = ?",
            (subject, int(version)),
        )
        row = cur.fetchone()
        return self._row_to_version(row) if row else None

    def latest(self, subject: str) -> Optional[SchemaVersion]:
        cur = self._conn.execute(
            "SELECT subject, version, schema_json, format, created_at "
            "FROM schemas WHERE subject = ? "
            "ORDER BY version DESC LIMIT 1",
            (subject,),
        )
        row = cur.fetchone()
        return self._row_to_version(row) if row else None

    def list_subjects(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT subject FROM schemas ORDER BY subject")
        return [r[0] for r in cur.fetchall()]

    def list_versions(self, subject: str) -> list[int]:
        cur = self._conn.execute(
            "SELECT version FROM schemas WHERE subject = ? ORDER BY version",
            (subject,),
        )
        return [int(r[0]) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_version(row: tuple) -> SchemaVersion:
        subject, version, schema_json, fmt, created_at = row
        return SchemaVersion(
            subject=str(subject),
            version=int(version),
            schema=json.loads(schema_json),
            format=str(fmt),
            created_at=float(created_at),
        )
