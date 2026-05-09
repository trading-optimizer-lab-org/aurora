"""Tests for aurora.core.logging."""
from __future__ import annotations
import json
import logging
import logging.handlers
import os

import pytest

from aurora.core.logging import (
    configure_logging,
    get_logger,
    log_event,
    has_structlog,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging state between tests."""
    import aurora.core.logging as ql
    ql._CONFIGURED = False
    root = logging.getLogger("aurora")
    for h in list(root.handlers):
        root.removeHandler(h)
    yield
    ql._CONFIGURED = False
    for h in list(root.handlers):
        root.removeHandler(h)


def test_get_logger_idempotent():
    a = get_logger("engine")
    b = get_logger("engine")
    assert a is b
    # same actual python logger (name normalized to quantforge.engine)
    assert a.name == "aurora.engine"


def test_get_logger_root():
    log = get_logger()
    assert log.name == "aurora"


def test_configure_level(tmp_path):
    f = tmp_path / "lvl.log"
    configure_logging(level="WARNING", log_file=f, rotating=False)
    log = get_logger("levelcheck")
    log.debug("should_skip")
    log.warning("should_pass")
    for h in logging.getLogger("aurora").handlers:
        h.flush()
    content = f.read_text(encoding="utf-8")
    assert "should_skip" not in content
    assert "should_pass" in content


def test_configure_file_writes(tmp_path):
    f = tmp_path / "forge.log"
    configure_logging(level="INFO", log_file=f, json_format=False, rotating=False)
    log = get_logger("filecheck")
    log.info("hello_world", extra={"kv": {"k": 1}})
    # Flush handlers
    for h in logging.getLogger("aurora").handlers:
        h.flush()
    content = f.read_text(encoding="utf-8")
    assert "hello_world" in content
    assert "k=1" in content


def test_json_format(tmp_path):
    f = tmp_path / "forge.json"
    configure_logging(level="INFO", log_file=f, json_format=True, rotating=False)
    log = get_logger("jsoncheck")
    log.info("backtest_done", extra={"kv": {"calmar": 2.5, "sharpe": 1.8}})
    for h in logging.getLogger("aurora").handlers:
        h.flush()
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "expected at least one log line"
    parsed = json.loads(lines[0])
    assert parsed["msg"] == "backtest_done"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "aurora.jsoncheck"
    assert parsed["kv"] == {"calmar": 2.5, "sharpe": 1.8}
    assert "ts" in parsed


def test_log_event_helper(tmp_path):
    f = tmp_path / "evt.log"
    configure_logging(level="INFO", log_file=f, json_format=True, rotating=False)
    log = get_logger("eventcheck")
    log_event(log, "trade_filled", symbol="SPY", price=420.5, qty=10)
    for h in logging.getLogger("aurora").handlers:
        h.flush()
    parsed = json.loads(f.read_text(encoding="utf-8").splitlines()[0])
    assert parsed["msg"] == "trade_filled"
    assert parsed["kv"]["symbol"] == "SPY"
    assert parsed["kv"]["price"] == 420.5
    assert parsed["kv"]["qty"] == 10


def test_rotating_smoke(tmp_path):
    """Smoke test rotating handler installs without error."""
    f = tmp_path / "rot.log"
    configure_logging(level="INFO", log_file=f, json_format=False, rotating=True)
    log = get_logger("rotcheck")
    log.info("rotating_smoke")
    handlers = logging.getLogger("aurora").handlers
    has_rotating = any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers
    )
    assert has_rotating
    for h in handlers:
        h.flush()
        h.close()


def test_text_format_kv_appears(tmp_path):
    f = tmp_path / "text.log"
    configure_logging(level="INFO", log_file=f, json_format=False, rotating=False)
    log = get_logger("textcheck")
    log.info("metric_log", extra={"kv": {"calmar": 2.5, "sharpe": 1.8}})
    for h in logging.getLogger("aurora").handlers:
        h.flush()
    content = f.read_text(encoding="utf-8")
    assert "metric_log" in content
    assert "calmar=2.5" in content
    assert "sharpe=1.8" in content
    assert "INFO" in content
    assert "aurora.textcheck" in content


def test_has_structlog_returns_bool():
    assert isinstance(has_structlog(), bool)


def test_reconfigure_replaces_handlers(tmp_path):
    f1 = tmp_path / "a.log"
    f2 = tmp_path / "b.log"
    configure_logging(level="INFO", log_file=f1, rotating=False)
    h1 = list(logging.getLogger("aurora").handlers)
    configure_logging(level="INFO", log_file=f2, rotating=False)
    h2 = list(logging.getLogger("aurora").handlers)
    # Should be fresh handlers, not appended
    assert len(h2) == 2  # console + file
    assert h1 != h2
