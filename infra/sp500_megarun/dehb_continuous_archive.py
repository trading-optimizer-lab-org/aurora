"""Immutable SQLite history for segmented continuous DEHB campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import local
from typing import Any, Iterable, Mapping
import zlib

from aurora.infra.sp500_megarun.dehb_continuous_models import (
    EvaluationCacheKeyV2,
    EvaluationResultV2,
    StrategyEvaluationKeyV1,
)
from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    scientific_result_sha256,
)


class HistoricalArchiveError(RuntimeError):
    """Base error for immutable historical caches."""


class HistoricalArchiveConflictError(HistoricalArchiveError):
    """Raised when one historical identity has contradictory evidence."""


class HistoricalArchiveIntegrityError(HistoricalArchiveError):
    """Raised when an archive or its manifest is incomplete or altered."""


@dataclass(frozen=True)
class ArchiveIdentityV1:
    campaign_id: str
    scientific_contract_sha256: str
    code_commit_sha: str
    train_manifest_sha256: str
    train_spy_sha256: str
    numeric_profile_sha256: str
    validation_opened: bool = False
    locked_opened: bool = False
    schema_version: int = 1


@dataclass(frozen=True)
class HistoricalArchiveReceiptV1:
    database_sha256: str
    evaluation_count: int
    strategy_count: int
    result_row_count: int
    schema_version: int = 1


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _encoded(value: Mapping[str, Any]) -> tuple[bytes, str]:
    raw = _canonical_bytes(dict(value))
    return zlib.compress(raw, level=9), hashlib.sha256(raw).hexdigest()


def _decoded(blob: bytes, expected_sha256: str) -> dict[str, Any]:
    try:
        raw = zlib.decompress(bytes(blob))
    except zlib.error as exc:
        raise HistoricalArchiveIntegrityError(
            "CONTINUOUS_ARCHIVE_PAYLOAD_INVALID"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != str(expected_sha256):
        raise HistoricalArchiveIntegrityError(
            "CONTINUOUS_ARCHIVE_PAYLOAD_HASH_MISMATCH"
        )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise HistoricalArchiveIntegrityError(
            "CONTINUOUS_ARCHIVE_PAYLOAD_MAPPING_REQUIRED"
        )
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE archive_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE evaluation_cache (
            cache_key_sha256 TEXT PRIMARY KEY,
            key_payload BLOB NOT NULL,
            key_payload_sha256 TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            result_payload BLOB NOT NULL,
            result_payload_sha256 TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE strategy_cache (
            strategy_key_sha256 TEXT PRIMARY KEY,
            key_payload BLOB NOT NULL,
            key_payload_sha256 TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            result_payload BLOB NOT NULL,
            result_payload_sha256 TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE reducer_rows (
            proposal_identity TEXT PRIMARY KEY,
            row_payload BLOB NOT NULL,
            row_payload_sha256 TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )


def _insert_cache_row(
    connection: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    key_sha256: str,
    key_payload: Mapping[str, Any],
    result_sha256: str,
    result_payload: Mapping[str, Any],
    conflict_message: str,
) -> None:
    encoded_key, key_payload_sha = _encoded(key_payload)
    encoded_result, result_payload_sha = _encoded(result_payload)
    existing = connection.execute(
        f"SELECT key_payload_sha256, result_sha256, result_payload_sha256 "
        f"FROM {table} WHERE {key_column} = ?",
        (key_sha256,),
    ).fetchone()
    identity = (key_payload_sha, str(result_sha256), result_payload_sha)
    if existing is not None:
        if tuple(str(value) for value in existing) != identity:
            raise HistoricalArchiveConflictError(conflict_message)
        return
    connection.execute(
        f"INSERT INTO {table} ({key_column}, key_payload, key_payload_sha256, "
        "result_sha256, result_payload, result_payload_sha256) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            key_sha256,
            encoded_key,
            key_payload_sha,
            str(result_sha256),
            encoded_result,
            result_payload_sha,
        ),
    )


def _proposal_identity(row: Mapping[str, Any]) -> str:
    required = ("island_id", "batch_sequence", "batch_slot")
    if any(field not in row for field in required):
        raise HistoricalArchiveIntegrityError(
            "CONTINUOUS_ARCHIVE_PROPOSAL_IDENTITY_MISSING"
        )
    return f"{row['island_id']}:{int(row['batch_sequence'])}:{int(row['batch_slot'])}"


def write_sqlite_historical_cache(
    *,
    database_path: Path,
    manifest_path: Path,
    identity: ArchiveIdentityV1,
    evaluation_entries: Iterable[tuple[EvaluationCacheKeyV2, EvaluationResultV2]],
    strategy_entries: Iterable[tuple[StrategyEvaluationKeyV1, str, Mapping[str, Any]]],
    result_rows: Iterable[Mapping[str, Any]],
) -> HistoricalArchiveReceiptV1:
    """Write one deterministic, conflict-detecting historical cache."""

    if identity.validation_opened or identity.locked_opened:
        raise HistoricalArchiveIntegrityError("CONTINUOUS_ARCHIVE_BOUNDARY_OPEN")
    database = Path(database_path).resolve()
    manifest = Path(manifest_path).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    with sqlite3.connect(database) as connection:
        _create_schema(connection)
        connection.execute(
            "INSERT INTO archive_meta(key, value) VALUES ('identity', ?)",
            (_canonical_bytes(asdict(identity)).decode("utf-8"),),
        )
        for key, result in evaluation_entries:
            if result.key.sha256 != key.sha256:
                raise HistoricalArchiveConflictError(
                    "CONTINUOUS_ARCHIVE_EVALUATION_KEY_MISMATCH"
                )
            _insert_cache_row(
                connection,
                table="evaluation_cache",
                key_column="cache_key_sha256",
                key_sha256=key.sha256,
                key_payload=key.payload,
                result_sha256=result.result_sha256,
                result_payload=result.result,
                conflict_message="CONTINUOUS_ARCHIVE_EVALUATION_CONFLICT",
            )
        for key, result_sha, result in strategy_entries:
            if scientific_result_sha256(result) != str(result_sha):
                raise HistoricalArchiveConflictError(
                    "CONTINUOUS_ARCHIVE_STRATEGY_RESULT_HASH_MISMATCH"
                )
            _insert_cache_row(
                connection,
                table="strategy_cache",
                key_column="strategy_key_sha256",
                key_sha256=key.sha256,
                key_payload=key.payload,
                result_sha256=str(result_sha),
                result_payload=result,
                conflict_message="CONTINUOUS_ARCHIVE_STRATEGY_CONFLICT",
            )
        for raw_row in result_rows:
            row = dict(raw_row)
            if row.get("validation_opened") is not False or row.get(
                "locked_opened"
            ) is not False:
                raise HistoricalArchiveIntegrityError(
                    "CONTINUOUS_ARCHIVE_RESULT_BOUNDARY_OPEN"
                )
            proposal_id = _proposal_identity(row)
            encoded_row, row_sha = _encoded(row)
            existing = connection.execute(
                "SELECT row_payload_sha256 FROM reducer_rows "
                "WHERE proposal_identity = ?",
                (proposal_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != row_sha:
                    raise HistoricalArchiveConflictError(
                        "CONTINUOUS_ARCHIVE_REDUCER_ROW_CONFLICT"
                    )
                continue
            connection.execute(
                "INSERT INTO reducer_rows VALUES (?, ?, ?)",
                (proposal_id, encoded_row, row_sha),
            )
        connection.commit()
        connection.execute("VACUUM")
        counts = tuple(
            int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in ("evaluation_cache", "strategy_cache", "reducer_rows")
        )
    database_sha = _file_sha256(database)
    receipt = HistoricalArchiveReceiptV1(database_sha, *counts)
    manifest_payload = {
        "schema_version": 1,
        "identity": asdict(identity),
        "database_sha256": database_sha,
        "database_bytes": database.stat().st_size,
        "evaluation_count": receipt.evaluation_count,
        "strategy_count": receipt.strategy_count,
        "result_row_count": receipt.result_row_count,
        "validation_opened": False,
        "locked_opened": False,
    }
    manifest.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


class SqliteHistoricalCacheV1:
    """Thread-safe read-only lookup over one verified historical cache."""

    def __init__(
        self,
        *,
        database_path: Path,
        manifest_path: Path,
        expected_identity: ArchiveIdentityV1,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if manifest.get("identity") != asdict(expected_identity):
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_IDENTITY_MISMATCH"
            )
        if manifest.get("validation_opened") is not False or manifest.get(
            "locked_opened"
        ) is not False:
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_BOUNDARY_OPEN"
            )
        if _file_sha256(self.database_path) != str(manifest.get("database_sha256")):
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_DATABASE_HASH_MISMATCH"
            )
        self._local = local()

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True)
            connection.execute("PRAGMA query_only=ON")
            self._local.connection = connection
        return connection

    def get_evaluation(self, key: EvaluationCacheKeyV2) -> dict[str, Any] | None:
        row = self._connection().execute(
            "SELECT key_payload, key_payload_sha256, result_sha256, "
            "result_payload, result_payload_sha256 FROM evaluation_cache "
            "WHERE cache_key_sha256 = ?",
            (key.sha256,),
        ).fetchone()
        if row is None:
            return None
        stored_key = _decoded(row[0], row[1])
        if stored_key != dict(key.payload):
            raise HistoricalArchiveConflictError(
                "CONTINUOUS_ARCHIVE_EVALUATION_KEY_CONFLICT"
            )
        result = _decoded(row[3], row[4])
        checked = EvaluationResultV2.build(key=key, result=result)
        if checked.result_sha256 != str(row[2]):
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_EVALUATION_RESULT_HASH_MISMATCH"
            )
        return dict(checked.result)

    def get_strategy(self, key: StrategyEvaluationKeyV1) -> dict[str, Any] | None:
        row = self._connection().execute(
            "SELECT key_payload, key_payload_sha256, result_sha256, "
            "result_payload, result_payload_sha256 FROM strategy_cache "
            "WHERE strategy_key_sha256 = ?",
            (key.sha256,),
        ).fetchone()
        if row is None:
            return None
        stored_key = _decoded(row[0], row[1])
        if stored_key != dict(key.payload):
            raise HistoricalArchiveConflictError(
                "CONTINUOUS_ARCHIVE_STRATEGY_KEY_CONFLICT"
            )
        result = _decoded(row[3], row[4])
        if scientific_result_sha256(result) != str(row[2]):
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_STRATEGY_RESULT_HASH_MISMATCH"
            )
        return result

    def result_rows(self) -> list[dict[str, Any]]:
        rows = [
            _decoded(payload, payload_sha)
            for payload, payload_sha in self._connection().execute(
                "SELECT row_payload, row_payload_sha256 FROM reducer_rows "
                "ORDER BY proposal_identity"
            ).fetchall()
        ]
        if any(
            row.get("validation_opened") is not False
            or row.get("locked_opened") is not False
            for row in rows
        ):
            raise HistoricalArchiveIntegrityError(
                "CONTINUOUS_ARCHIVE_RESULT_BOUNDARY_OPEN"
            )
        return rows

    def evaluation_entries(
        self,
    ) -> list[tuple[EvaluationCacheKeyV2, EvaluationResultV2]]:
        entries: list[tuple[EvaluationCacheKeyV2, EvaluationResultV2]] = []
        for key_sha, key_blob, key_payload_sha, result_sha, result_blob, result_payload_sha in (
            self._connection()
            .execute(
                "SELECT cache_key_sha256, key_payload, key_payload_sha256, "
                "result_sha256, result_payload, result_payload_sha256 "
                "FROM evaluation_cache ORDER BY cache_key_sha256"
            )
            .fetchall()
        ):
            key = EvaluationCacheKeyV2(
                sha256=str(key_sha),
                payload=_decoded(key_blob, key_payload_sha),
            )
            result = EvaluationResultV2.build(
                key=key,
                result=_decoded(result_blob, result_payload_sha),
            )
            if result.result_sha256 != str(result_sha):
                raise HistoricalArchiveIntegrityError(
                    "CONTINUOUS_ARCHIVE_EVALUATION_RESULT_HASH_MISMATCH"
                )
            entries.append((key, result))
        return entries

    def strategy_entries(
        self,
    ) -> list[tuple[StrategyEvaluationKeyV1, str, dict[str, Any]]]:
        entries: list[tuple[StrategyEvaluationKeyV1, str, dict[str, Any]]] = []
        for key_sha, key_blob, key_payload_sha, result_sha, result_blob, result_payload_sha in (
            self._connection()
            .execute(
                "SELECT strategy_key_sha256, key_payload, key_payload_sha256, "
                "result_sha256, result_payload, result_payload_sha256 "
                "FROM strategy_cache ORDER BY strategy_key_sha256"
            )
            .fetchall()
        ):
            key = StrategyEvaluationKeyV1(
                sha256=str(key_sha),
                payload=_decoded(key_blob, key_payload_sha),
            )
            result = _decoded(result_blob, result_payload_sha)
            if scientific_result_sha256(result) != str(result_sha):
                raise HistoricalArchiveIntegrityError(
                    "CONTINUOUS_ARCHIVE_STRATEGY_RESULT_HASH_MISMATCH"
                )
            entries.append((key, str(result_sha), result))
        return entries


__all__ = [
    "ArchiveIdentityV1",
    "HistoricalArchiveConflictError",
    "HistoricalArchiveError",
    "HistoricalArchiveIntegrityError",
    "HistoricalArchiveReceiptV1",
    "SqliteHistoricalCacheV1",
    "write_sqlite_historical_cache",
]
