"""Structured logging for QuantForge.

Stdlib-only by default. Optional `structlog` enrichment if installed.

Usage:
    from aurora.core.logging import get_logger, configure_logging, log_event

    configure_logging(level="INFO", log_file="logs/forge.log", json_format=False)
    log = get_logger(__name__)
    log.info("backtest_done", extra={"kv": {"calmar": 2.5, "sharpe": 1.8}})
    # or
    log_event(log, "backtest_done", calmar=2.5, sharpe=1.8)
"""
from __future__ import annotations
import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

# Detect optional structlog
try:
    import structlog  # type: ignore
    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False

_CONFIGURED = False
_ROOT_NAME = "aurora"


class _KVTextFormatter(logging.Formatter):
    """Human readable: timestamp level logger: msg k1=v1 k2=v2."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        kv = getattr(record, "kv", None)
        if kv and isinstance(kv, dict):
            parts = " ".join(f"{k}={_fmt_val(v)}" for k, v in kv.items())
            return f"{base} {parts}"
        return base


class _JSONFormatter(logging.Formatter):
    """JSON lines: one record per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        kv = getattr(record, "kv", None)
        if kv and isinstance(kv, dict):
            payload["kv"] = kv
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _fmt_val(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, str) and " " in v:
        return f'"{v}"'
    return str(v)


def configure_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    json_format: bool = False,
    rotating: bool = True,
) -> None:
    """Configure root quantforge logger.

    Args:
        level: DEBUG | INFO | WARNING | ERROR
        log_file: optional path; if set, also write to file with rotation
        json_format: if True, JSON lines (for ingestion); else human readable
        rotating: if True, rotate daily, keep 7 days
    """
    global _CONFIGURED
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Wipe prior handlers so reconfigure is clean
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt: logging.Formatter = _JSONFormatter() if json_format else _KVTextFormatter()

    # Console handler always on stderr
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Optional file handler
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        if rotating:
            fh: logging.Handler = logging.handlers.TimedRotatingFileHandler(
                str(path),
                when="D",
                interval=1,
                backupCount=7,
                encoding="utf-8",
            )
        else:
            fh = logging.FileHandler(str(path), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # Don't bubble to root python logger (avoid double output)
    root.propagate = False

    # Optional structlog wiring (cosmetic; stdlib still drives output)
    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    _CONFIGURED = True


def get_logger(name: str = "aurora") -> logging.Logger:
    """Return configured logger. Idempotent — same name returns same instance.

    If configure_logging() never ran, sets a sane default (INFO, stderr, text).
    """
    if not _CONFIGURED:
        configure_logging()
    # Force quantforge namespace so child loggers inherit handlers
    if name != _ROOT_NAME and not name.startswith(_ROOT_NAME + "."):
        if name == "__main__" or name == "":
            name = _ROOT_NAME
        else:
            name = f"{_ROOT_NAME}.{name}"
    return logging.getLogger(name)


def log_event(log: logging.Logger, event: str, level: str = "INFO", **kv: Any) -> None:
    """Emit structured event with kv pairs.

    Equivalent to log.info(event, extra={"kv": kv}) but shorter.
    """
    log.log(getattr(logging, level.upper(), logging.INFO), event, extra={"kv": kv})


def has_structlog() -> bool:
    """Return True if structlog is available for richer formatting."""
    return _HAS_STRUCTLOG
