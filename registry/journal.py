"""SQLite trade journal for live deployment.

Stdlib sqlite3 only. Logs every trade fill (and pending orders) for live/paper
trading systems. Provides query, daily PnL aggregation, and position
reconstruction from the BUY/SELL log.

Schema:
    id INTEGER PRIMARY KEY
    timestamp TEXT (ISO)
    strategy_name TEXT
    strategy_version TEXT
    symbol TEXT
    side TEXT (BUY|SELL)
    quantity REAL
    fill_price REAL
    notional REAL          -- signed: BUY positive, SELL negative
    commission REAL
    slippage_bps REAL
    signal_value REAL
    status TEXT (PENDING|FILLED|CANCELED|REJECTED)
    order_id TEXT
    note TEXT
"""
from __future__ import annotations

import csv
import datetime as _dt
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

import pandas as pd

from aurora.core.sqlite_utils import _setup_sqlite


def _default_db_path() -> str:
    """Resolve the trade-journal DB path via runtime_paths (R75)."""
    from aurora.core.runtime_paths import cache_dir
    return str(cache_dir() / "trade_journal.db")


_DEFAULT_DB_PATH = _default_db_path()


_VALID_SIDES = {"BUY", "SELL"}
_VALID_STATUS = {"PENDING", "FILLED", "CANCELED", "REJECTED"}


@dataclass
class JournalEntry:
    id: int
    timestamp: str
    strategy_name: str
    strategy_version: Optional[str]
    symbol: str
    side: str
    quantity: float
    fill_price: float
    notional: float
    commission: float
    slippage_bps: float
    signal_value: float
    status: str
    order_id: Optional[str]
    note: str


def _signed_notional(side: str, quantity: float, fill_price: float) -> float:
    """BUY -> +qty*price, SELL -> -qty*price. Quantity is taken as magnitude."""
    mag = abs(float(quantity)) * float(fill_price)
    return mag if side == "BUY" else -mag


def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        id=int(row["id"]),
        timestamp=row["timestamp"],
        strategy_name=row["strategy_name"],
        strategy_version=row["strategy_version"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=float(row["quantity"]),
        fill_price=float(row["fill_price"]),
        notional=float(row["notional"]),
        commission=float(row["commission"]),
        slippage_bps=float(row["slippage_bps"]),
        signal_value=float(row["signal_value"]),
        status=row["status"],
        order_id=row["order_id"],
        note=row["note"] or "",
    )


class TradeJournal:
    """SQLite trade log for live deployment."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            strategy_version TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            fill_price REAL NOT NULL,
            notional REAL NOT NULL,
            commission REAL NOT NULL DEFAULT 0,
            slippage_bps REAL NOT NULL DEFAULT 0,
            signal_value REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            order_id TEXT,
            note TEXT NOT NULL DEFAULT ''
        )
    """

    INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_jr_strategy ON journal(strategy_name)",
        "CREATE INDEX IF NOT EXISTS idx_jr_symbol ON journal(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_jr_status ON journal(status)",
        "CREATE INDEX IF NOT EXISTS idx_jr_ts ON journal(timestamp DESC)",
    ]

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        _setup_sqlite(conn, mode="normal")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute(self.SCHEMA)
            for stmt in self.INDEXES:
                c.execute(stmt)

    # --- write ---

    def log_trade(self, strategy_name: str, symbol: str, side: str,
                  quantity: float, fill_price: float, signal_value: float,
                  commission: float = 0.0, slippage_bps: float = 0.0,
                  status: str = "FILLED",
                  strategy_version: Optional[str] = None,
                  order_id: Optional[str] = None,
                  note: str = "",
                  kind: str = "trade",
                  _now: Optional[_dt.datetime] = None) -> int:
        """Log a trade. Returns row ID.

        Notional is computed as signed: +qty*price for BUY, -qty*price for SELL.

        ``kind`` controls the closure-trade rule for ``fill_price == 0``:
        - ``"trade"`` (default): a zero fill_price is rejected.
        - ``"closure"``: explicit zero-cost offset (derivative flatten,
          option expiry-at-zero, futures roll close); allowed regardless of
          ``signal_value``.

        Previously a zero fill_price was implicitly accepted only when
        ``signal_value == 0``, which rejected legitimate derivatives flows
        (signal still active while booking a zero-cost close). The opt-in
        ``kind`` flag makes the intent explicit at the call site.

        ``_now`` is a test-only injection seam: pass an explicit
        ``datetime`` to control the recorded timestamp. Production callers
        should leave it None (defaults to UTC ``datetime.now``).
        """
        side = str(side).upper()
        status = str(status).upper()
        kind_norm = str(kind).lower()
        if side not in _VALID_SIDES:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if status not in _VALID_STATUS:
            raise ValueError(f"status must be one of {_VALID_STATUS}, got {status!r}")
        if kind_norm not in {"trade", "closure"}:
            raise ValueError(
                f"kind must be 'trade' or 'closure', got {kind!r}"
            )

        # Sin-guard: notional with NaN/inf price is meaningless and would
        # silently corrupt PnL aggregation downstream. Block at write time.
        # ``fill_price == 0`` is gated by the explicit ``kind="closure"``
        # opt-in. Negative prices remain rejected.
        try:
            fp = float(fill_price)
        except (TypeError, ValueError) as e:
            raise ValueError(f"fill_price must be a real number, got {fill_price!r}") from e
        if math.isnan(fp) or math.isinf(fp) or fp < 0.0:
            raise ValueError(
                f"price must be >= 0 and finite to record trade "
                f"(got fill_price={fill_price!r})"
            )
        if fp == 0.0 and kind_norm != "closure":
            raise ValueError(
                "fill_price == 0 is only allowed for closure trades; "
                "pass kind='closure' to explicitly opt in "
                f"(got fill_price={fill_price!r}, kind={kind!r})"
            )

        # Sin-guard: NaN / inf / non-positive quantities corrupt notional
        # and downstream position-history reconstruction. Reject up front
        # with a clear error rather than letting the bad value propagate
        # into SQLite and PnL aggregations.
        try:
            qty = float(quantity)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"quantity must be a real number, got {quantity!r}"
            ) from e
        if math.isnan(qty) or math.isinf(qty) or qty <= 0.0:
            raise ValueError(
                f"quantity must be a finite positive number to record trade "
                f"(got quantity={quantity!r})"
            )

        now = _now if _now is not None else _dt.datetime.now(tz=_dt.timezone.utc)
        ts = now.isoformat(timespec="seconds")
        notional = _signed_notional(side, quantity, fill_price)

        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO journal
                    (timestamp, strategy_name, strategy_version, symbol, side,
                     quantity, fill_price, notional, commission, slippage_bps,
                     signal_value, status, order_id, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts, strategy_name, strategy_version, symbol, side,
                    float(abs(quantity)), float(fill_price), notional,
                    float(commission), float(slippage_bps), float(signal_value),
                    status, order_id, note,
                ),
            )
            if cur.lastrowid is None:  # pragma: no cover - sqlite defensive
                raise RuntimeError("insert succeeded but sqlite did not return row id")
            return int(cur.lastrowid)

    def update_status(self, entry_id: int, status: str,
                      fill_price: Optional[float] = None) -> bool:
        """Update pending order status. If fill_price supplied, recompute notional."""
        status = str(status).upper()
        if status not in _VALID_STATUS:
            raise ValueError(f"status must be one of {_VALID_STATUS}, got {status!r}")

        # Mirror log_trade's fill_price validation: NaN/inf or negative
        # corrupt notional and downstream PnL aggregation. update_status
        # cannot opt into closure-mode (no kind flag), so fp == 0 is also
        # rejected here to keep the journal invariant.
        if fill_price is not None:
            try:
                fp = float(fill_price)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"fill_price must be a real number, got {fill_price!r}"
                ) from e
            if math.isnan(fp) or math.isinf(fp) or fp <= 0.0:
                raise ValueError(
                    f"fill_price must be a finite positive number to update trade "
                    f"(got fill_price={fill_price!r})"
                )

        with self._conn() as c:
            row = c.execute(
                "SELECT side, quantity FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return False
            if fill_price is not None:
                new_notional = _signed_notional(
                    row["side"], float(row["quantity"]), float(fill_price)
                )
                cur = c.execute(
                    """UPDATE journal
                       SET status = ?, fill_price = ?, notional = ?
                       WHERE id = ?""",
                    (status, float(fill_price), new_notional, entry_id),
                )
            else:
                cur = c.execute(
                    "UPDATE journal SET status = ? WHERE id = ?",
                    (status, entry_id),
                )
            return cur.rowcount > 0

    # --- read ---

    def get(self, entry_id: int) -> Optional[JournalEntry]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
            return _row_to_entry(row) if row else None

    def query(self, strategy_name: Optional[str] = None,
              symbol: Optional[str] = None,
              status: Optional[str] = None,
              since: Optional[str] = None,
              limit: int = 1000) -> list[JournalEntry]:
        """Filter entries; returns rows sorted by timestamp DESC."""
        clauses: list[str] = []
        params: list = []
        if strategy_name is not None:
            clauses.append("strategy_name = ?")
            params.append(strategy_name)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status).upper())
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM journal {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_entry(r) for r in rows]

    def count(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM journal").fetchone()
            return int(row["n"]) if row else 0

    # --- analytics ---

    def daily_pnl(self, strategy_name: Optional[str] = None) -> pd.DataFrame:
        """Aggregate realized cash-flow PnL per day.

        Sign convention
        ---------------
        BUY trades have negative cash flow (cash outflow): you pay cash to
        receive the asset. SELL trades have positive cash flow (cash inflow):
        you receive cash for delivering the asset. The stored ``notional``
        column mirrors the asset side (positive for BUY, negative for SELL),
        so realized cash flow per fill is ``-notional - commission``. Summing
        ``-notional - commission`` across fills inside a day yields realized
        daily cash-flow PnL. This is realized cash flow only and does not
        mark unrealized open positions to market.

        Returns a DataFrame with columns: date, pnl, n_trades.
        Only FILLED rows are included. Empty DataFrame if none.
        """
        params: list = ["FILLED"]
        clause = "WHERE status = ?"
        if strategy_name is not None:
            clause += " AND strategy_name = ?"
            params.append(strategy_name)

        sql = f"""
            SELECT substr(timestamp, 1, 10) AS date,
                   SUM(-notional - commission) AS pnl,
                   COUNT(*) AS n_trades
            FROM journal
            {clause}
            GROUP BY date
            ORDER BY date ASC
        """
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame(columns=["date", "pnl", "n_trades"])
        return pd.DataFrame([
            {"date": r["date"], "pnl": float(r["pnl"]), "n_trades": int(r["n_trades"])}
            for r in rows
        ])

    def position_history(self, symbol: str,
                         strategy_name: Optional[str] = None) -> pd.DataFrame:
        """Reconstruct position size over time from BUY/SELL log.

        BUY adds quantity, SELL subtracts. Only FILLED rows count.
        Returns DataFrame: timestamp, side, quantity, position (running sum).
        """
        params: list = [symbol, "FILLED"]
        clause = "WHERE symbol = ? AND status = ?"
        if strategy_name is not None:
            clause += " AND strategy_name = ?"
            params.append(strategy_name)

        sql = f"""
            SELECT timestamp, side, quantity, fill_price
            FROM journal
            {clause}
            ORDER BY timestamp ASC, id ASC
        """
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame(columns=["timestamp", "side", "quantity",
                                         "fill_price", "position"])
        records = []
        pos = 0.0
        for r in rows:
            q = float(r["quantity"])
            signed = q if r["side"] == "BUY" else -q
            pos += signed
            records.append({
                "timestamp": r["timestamp"],
                "side": r["side"],
                "quantity": q,
                "fill_price": float(r["fill_price"]),
                "position": pos,
            })
        return pd.DataFrame.from_records(records)

    # --- export ---

    def to_dataframe(self) -> pd.DataFrame:
        """All entries as DataFrame. Sorted by timestamp DESC."""
        cols = ["id", "timestamp", "strategy_name", "strategy_version",
                "symbol", "side", "quantity", "fill_price", "notional",
                "commission", "slippage_bps", "signal_value", "status",
                "order_id", "note"]
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM journal ORDER BY timestamp DESC"
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([
            {c: r[c] for c in cols} for r in rows
        ])

    def export_csv(self, path: str, **filters) -> int:
        """Export filtered entries to CSV. Returns row count.

        Accepts the same filters as `query`: strategy_name, symbol, status,
        since, limit (default 1_000_000 for export).
        """
        filters.setdefault("limit", 1_000_000)
        entries = self.query(**filters)
        cols = ["id", "timestamp", "strategy_name", "strategy_version",
                "symbol", "side", "quantity", "fill_price", "notional",
                "commission", "slippage_bps", "signal_value", "status",
                "order_id", "note"]
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for e in entries:
                writer.writerow({
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "strategy_name": e.strategy_name,
                    "strategy_version": e.strategy_version or "",
                    "symbol": e.symbol,
                    "side": e.side,
                    "quantity": e.quantity,
                    "fill_price": e.fill_price,
                    "notional": e.notional,
                    "commission": e.commission,
                    "slippage_bps": e.slippage_bps,
                    "signal_value": e.signal_value,
                    "status": e.status,
                    "order_id": e.order_id or "",
                    "note": e.note,
                })
        return len(entries)
