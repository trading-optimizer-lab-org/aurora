"""Tests for quantforge.monitoring.alerts.

Run::

    cd "C:/Users/HP/MODELO SP500"
    uv run pytest quantforge/tests/test_alerts.py -v

No real network or SMTP — every dispatch path is mocked.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import numpy as np
import pytest

from quantforge.monitoring.alerts import (
    Alert,
    AlertConfig,
    AlertEngine,
    AlertRule,
    compute_daily_loss,
    compute_drift_metric,
    compute_max_dd,
    default_rules,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
class _FakeClock:
    """Deterministic clock for cooldown tests."""

    def __init__(self, start: datetime):
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


def _make_engine(rules, clock=None, **cfg_kwargs) -> AlertEngine:
    cfg = AlertConfig(rules=list(rules), **cfg_kwargs)
    return AlertEngine(cfg, now_func=clock)


# --------------------------------------------------------------------------- #
# 1. Rule evaluation                                                          #
# --------------------------------------------------------------------------- #
def test_rule_eval_above_threshold():
    """max_dd=0.25 with threshold 0.20 (>) must trigger."""
    rule = AlertRule(
        name="dd_warn", metric="max_dd", threshold=0.20,
        operator=">", severity="critical",
    )
    engine = _make_engine([rule])
    triggered = engine.evaluate({"max_dd": 0.25})
    assert len(triggered) == 1
    a = triggered[0]
    assert a.rule_name == "dd_warn"
    assert a.severity == "critical"
    assert a.metadata["value"] == pytest.approx(0.25)
    assert a.metadata["threshold"] == pytest.approx(0.20)


def test_rule_eval_below_threshold():
    """max_dd=0.10 below 0.20 → no trigger."""
    rule = AlertRule(
        name="dd_warn", metric="max_dd", threshold=0.20, operator=">",
    )
    engine = _make_engine([rule])
    assert engine.evaluate({"max_dd": 0.10}) == []


def test_rule_eval_skips_missing_metric():
    """Rules referencing absent metrics are silently skipped."""
    rule = AlertRule(name="x", metric="nonexistent", threshold=0.5)
    engine = _make_engine([rule])
    assert engine.evaluate({"unrelated": 1.0}) == []


def test_rule_eval_all_operators():
    """All five operators evaluate correctly."""
    cases = [
        (">", 1.0, 2.0, True),
        (">", 1.0, 1.0, False),
        ("<", 1.0, 0.5, True),
        (">=", 1.0, 1.0, True),
        ("<=", 1.0, 1.0, True),
        ("==", 1.0, 1.0, True),
        ("==", 1.0, 1.5, False),
    ]
    for op, threshold, value, expected in cases:
        rule = AlertRule(name="r", metric="m", threshold=threshold, operator=op)
        engine = _make_engine([rule])
        triggered = engine.evaluate({"m": value})
        assert bool(triggered) is expected, (op, threshold, value)


def test_rule_invalid_operator_raises():
    with pytest.raises(ValueError):
        AlertRule(name="bad", metric="m", threshold=1.0, operator="!=")


def test_rule_invalid_severity_raises():
    with pytest.raises(ValueError):
        AlertRule(name="bad", metric="m", threshold=1.0, severity="emergency")


def test_alert_severity_levels():
    """info, warn, critical are all valid; bad strings raise."""
    for sev in ("info", "warn", "critical"):
        rule = AlertRule(name="r", metric="m", threshold=0.0, operator=">", severity=sev)
        engine = _make_engine([rule])
        triggered = engine.evaluate({"m": 1.0})
        assert triggered[0].severity == sev


# --------------------------------------------------------------------------- #
# 2. Cooldown                                                                 #
# --------------------------------------------------------------------------- #
def test_cooldown_suppresses(monkeypatch):
    """Two fires within the cooldown window: second is suppressed."""
    clock = _FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    rule = AlertRule(
        name="dd_warn", metric="max_dd", threshold=0.20,
        cooldown_seconds=3600,
    )
    engine = _make_engine([rule], clock=clock)
    alert = Alert(
        rule_name="dd_warn", severity="warn",
        message="dd breach", timestamp=clock(),
    )

    assert engine.fire(alert) is True
    # No time advance — second fire must be suppressed.
    assert engine.fire(alert) is False


def test_cooldown_releases():
    """After cooldown window passes, the same rule can fire again."""
    clock = _FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    rule = AlertRule(
        name="dd_warn", metric="max_dd", threshold=0.20,
        cooldown_seconds=3600,
    )
    engine = _make_engine([rule], clock=clock)
    alert = Alert(
        rule_name="dd_warn", severity="warn",
        message="dd breach", timestamp=clock(),
    )

    assert engine.fire(alert) is True
    clock.advance(3601)  # past cooldown
    assert engine.fire(alert) is True


def test_cooldown_zero_disables():
    """cooldown_seconds=0 means every fire is allowed."""
    clock = _FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    rule = AlertRule(
        name="r", metric="m", threshold=0.0, cooldown_seconds=0,
    )
    engine = _make_engine([rule], clock=clock)
    a = Alert(rule_name="r", severity="warn", message="x", timestamp=clock())
    for _ in range(5):
        assert engine.fire(a) is True


# --------------------------------------------------------------------------- #
# 3. Email dispatch                                                           #
# --------------------------------------------------------------------------- #
def test_email_uses_env_password(monkeypatch):
    """SMTP login must be called with the password from the configured env var."""
    monkeypatch.setenv("QFORGE_SMTP_PASSWORD", "s3cret-from-env")

    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="quant@example.com",
        smtp_to=["alerts@example.com"],
        smtp_password_env="QFORGE_SMTP_PASSWORD",
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    fake_smtp = mock.MagicMock()
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False

    with mock.patch("smtplib.SMTP", return_value=cm) as smtp_cls:
        engine.send_email(alert)

    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
    fake_smtp.starttls.assert_called_once()
    fake_smtp.login.assert_called_once_with("quant@example.com", "s3cret-from-env")
    fake_smtp.send_message.assert_called_once()


def test_email_missing_password(monkeypatch):
    """env var unset → clear RuntimeError, no silent failure."""
    monkeypatch.delenv("QFORGE_SMTP_PASSWORD", raising=False)
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com",
        smtp_user="u@example.com",
        smtp_to=["alerts@example.com"],
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="QFORGE_SMTP_PASSWORD"):
        engine.send_email(alert)


def test_email_no_password_in_logs(monkeypatch, caplog):
    """Even when send_email is invoked via fire(), the password env value
    must never appear in log output."""
    monkeypatch.setenv("QFORGE_SMTP_PASSWORD", "do-not-leak-this")
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com",
        smtp_user="u@example.com",
        smtp_to=["alerts@example.com"],
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    fake_smtp = mock.MagicMock()
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with caplog.at_level("DEBUG"), mock.patch("smtplib.SMTP", return_value=cm):
        engine.fire(alert)

    assert "do-not-leak-this" not in caplog.text


# --------------------------------------------------------------------------- #
# 4. Webhook dispatch                                                         #
# --------------------------------------------------------------------------- #
def _capture_webhook_call(engine: AlertEngine, alert: Alert, url: str) -> dict:
    """Helper: invoke send_webhook with urlopen mocked, return parsed payload."""
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = b""
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_resp
    cm.__exit__.return_value = False

    with mock.patch("urllib.request.urlopen", return_value=cm) as uo:
        engine.send_webhook(alert, url=url)

    assert uo.called
    req = uo.call_args[0][0]
    return json.loads(req.data.decode("utf-8"))


def test_webhook_slack_payload():
    rule = AlertRule(name="dd_warn", metric="max_dd", threshold=0.20)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="dd_warn",
        severity="warn",
        message="dd breach",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={"value": 0.25, "threshold": 0.20},
    )
    payload = _capture_webhook_call(
        engine, alert, "https://hooks.slack.com/services/T000/B000/XXX",
    )
    # Slack-specific shape
    assert "text" in payload
    assert payload["text"] == "dd breach"
    assert "attachments" in payload
    att = payload["attachments"][0]
    assert att["title"] == "dd_warn"
    assert "color" in att
    assert any(f["title"] == "severity" and f["value"] == "warn" for f in att["fields"])


def test_webhook_discord_payload():
    rule = AlertRule(name="dd_warn", metric="max_dd", threshold=0.20)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="dd_warn",
        severity="critical",
        message="dd breach",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={"value": 0.25},
    )
    payload = _capture_webhook_call(
        engine, alert, "https://discord.com/api/webhooks/123/abc",
    )
    # Discord-specific shape: "content" present, no "text"
    assert "content" in payload
    assert payload["content"] == "dd breach"
    assert "text" not in payload
    assert "embeds" in payload
    emb = payload["embeds"][0]
    assert emb["title"] == "dd_warn"


def test_webhook_generic_payload():
    """Unknown hostname gets a generic JSON envelope."""
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="r",
        severity="info",
        message="hello",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={"k": "v"},
    )
    payload = _capture_webhook_call(engine, alert, "https://example.com/hook")
    assert payload["rule_name"] == "r"
    assert payload["severity"] == "info"
    assert payload["message"] == "hello"
    assert payload["metadata"] == {"k": "v"}


def test_fire_dispatches_to_all_webhooks():
    """fire() must POST to every configured webhook URL."""
    rule = AlertRule(name="r", metric="m", threshold=0.0, cooldown_seconds=0)
    engine = _make_engine(
        [rule],
        webhook_urls=[
            "https://hooks.slack.com/services/T/B/X",
            "https://discord.com/api/webhooks/1/abc",
            "https://example.com/generic",
        ],
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = b""
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_resp
    cm.__exit__.return_value = False

    with mock.patch("urllib.request.urlopen", return_value=cm) as uo:
        assert engine.fire(alert) is True

    assert uo.call_count == 3


# --------------------------------------------------------------------------- #
# 5. Metric helpers                                                           #
# --------------------------------------------------------------------------- #
def test_drift_metric_zero_for_identical():
    """Identical distributions → drift 0."""
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 500)
    assert compute_drift_metric(ref, ref) == pytest.approx(0.0)


def test_drift_metric_detects_mean_shift():
    """Shifted distribution → positive drift roughly equal to shift / sigma."""
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 1000)
    cur = rng.normal(0.5, 1, 1000)
    drift = compute_drift_metric(ref, cur)
    # ~0.5 sigma shift; allow generous tolerance for finite samples.
    assert 0.3 < drift < 0.7


def test_drift_metric_handles_zero_std():
    """Constant reference distribution falls back to abs mean diff."""
    ref = [1.0, 1.0, 1.0, 1.0]
    cur = [2.0, 2.0, 2.0]
    assert compute_drift_metric(ref, cur) == pytest.approx(1.0)


def test_drift_metric_empty_inputs():
    assert compute_drift_metric([], [1, 2, 3]) == 0.0
    assert compute_drift_metric([1, 2], []) == 0.0


def test_daily_loss_metric():
    """Hand-computed: 100 → 95 = -5%."""
    eq = [100.0, 102.0, 95.0]
    assert compute_daily_loss(eq) == pytest.approx((95.0 - 102.0) / 102.0)


def test_daily_loss_short_curve():
    """Fewer than 2 points → 0 (no signal)."""
    assert compute_daily_loss([100.0]) == 0.0
    assert compute_daily_loss([]) == 0.0


def test_max_dd_metric():
    """Peak 110 → trough 88 → drawdown = 0.20."""
    eq = [100.0, 110.0, 105.0, 88.0, 95.0]
    assert compute_max_dd(eq) == pytest.approx(0.20)


def test_max_dd_monotonic_up_is_zero():
    eq = [100.0, 101.0, 102.0, 110.0]
    assert compute_max_dd(eq) == pytest.approx(0.0)


def test_max_dd_empty():
    assert compute_max_dd([]) == 0.0


# --------------------------------------------------------------------------- #
# 6. Defaults                                                                 #
# --------------------------------------------------------------------------- #
def test_default_rules_match_spec():
    rules = {r.name: r for r in default_rules()}
    assert rules["drift_warn"].threshold == 0.05
    assert rules["drift_warn"].operator == ">"
    assert rules["drift_warn"].severity == "warn"

    assert rules["max_dd_critical"].threshold == 0.20
    assert rules["max_dd_critical"].severity == "critical"

    assert rules["daily_loss_warn"].threshold == -0.05
    assert rules["daily_loss_warn"].operator == "<"

    assert rules["sharpe_warn"].metric == "sharpe"
    assert rules["sharpe_warn"].threshold == 0.0
    assert rules["sharpe_warn"].operator == "<"


def test_smtp_uses_default_ssl_context(monkeypatch):
    """STARTTLS must be invoked with the system default SSL context so
    certificate + hostname verification is enforced.
    """
    import ssl

    monkeypatch.setenv("QFORGE_SMTP_PASSWORD", "p")
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com",
        smtp_user="u@example.com",
        smtp_to=["alerts@example.com"],
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    fake_smtp = mock.MagicMock()
    fake_smtp.starttls.return_value = (220, b"Ready to start TLS")
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False

    with mock.patch("smtplib.SMTP", return_value=cm):
        engine.send_email(alert)

    fake_smtp.starttls.assert_called_once()
    _, kwargs = fake_smtp.starttls.call_args
    ctx = kwargs.get("context")
    assert isinstance(ctx, ssl.SSLContext), (
        "starttls must receive a real ssl.SSLContext, got "
        f"{type(ctx).__name__}"
    )
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_webhook_lookalike_host_rejected():
    """A look-alike hostname like ``slack.evil.com`` must NOT be treated as
    Slack — the generic JSON envelope is used instead, so a phishing host
    cannot trick the engine into rendering Slack-shaped payloads.
    """
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="r", severity="info", message="hello",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={},
    )
    payload = _capture_webhook_call(engine, alert, "https://slack.evil.com/hook")
    # Generic envelope — no Slack-specific keys.
    assert "attachments" not in payload
    assert "rule_name" in payload

    payload2 = _capture_webhook_call(
        engine, alert, "https://discord-fake.example.com/hook",
    )
    assert "embeds" not in payload2
    assert "rule_name" in payload2


def test_webhook_rejects_non_https():
    """A ``http://`` webhook URL must be rejected unless the operator opts
    in via ``AlertConfig.allow_http_webhooks``.
    """
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="r", severity="info", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="https"):
        engine.send_webhook(alert, url="http://example.com/hook")
    # An unsupported scheme is also rejected.
    with pytest.raises(ValueError, match="https"):
        engine.send_webhook(alert, url="ftp://example.com/hook")


def test_alert_config_rejects_duplicate_rule_names():
    """``AlertConfig`` must reject duplicate rule names so cooldown
    bookkeeping cannot key on an ambiguous identifier.
    """
    a = AlertRule(name="dup", metric="m", threshold=0.0)
    b = AlertRule(name="dup", metric="m", threshold=1.0)
    with pytest.raises(ValueError, match="duplicate"):
        AlertConfig(rules=[a, b])


def test_eq_operator_uses_isclose_for_floats():
    """``==`` against a float threshold must use a tolerance rather than
    bitwise equality so 0.1 + 0.2 ~= 0.3 is detected.
    """
    rule = AlertRule(name="eq", metric="m", threshold=0.3, operator="==")
    engine = _make_engine([rule])
    triggered = engine.evaluate({"m": 0.1 + 0.2})
    assert len(triggered) == 1, "math.isclose path should fire"


def test_evaluate_with_default_rules_real_metrics():
    """End-to-end: defaults should fire on a clearly bad set of metrics."""
    engine = _make_engine(default_rules())
    triggered = engine.evaluate({
        "drift": 0.10,        # > 0.05
        "max_dd": 0.30,       # > 0.20
        "daily_loss": -0.07,  # < -0.05
        "sharpe": -0.5,       # < 0
    })
    fired_names = {a.rule_name for a in triggered}
    assert fired_names == {
        "drift_warn", "max_dd_critical", "daily_loss_warn", "sharpe_warn",
    }


# --------------------------------------------------------------------------- #
# Round V regression: tighter Discord allowlist + STARTTLS structural check.  #
# --------------------------------------------------------------------------- #
def test_webhook_discordapp_dropped_from_allowlist():
    """Round V: ``discordapp.com`` (deprecated alias) must NOT receive a
    Discord-formatted payload. Only ``discord.com``, ``canary.discord.com``,
    and ``ptb.discord.com`` are allowlisted.
    """
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="r", severity="info", message="hello",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={},
    )
    # Bare ``discordapp.com`` -> generic envelope, not Discord-shaped.
    payload = _capture_webhook_call(engine, alert, "https://discordapp.com/hook")
    assert "embeds" not in payload
    assert "rule_name" in payload
    # ``foo.discordapp.com`` -> generic envelope.
    payload2 = _capture_webhook_call(
        engine, alert, "https://foo.discordapp.com/hook",
    )
    assert "embeds" not in payload2
    # Arbitrary subdomain of discord.com NOT in {canary, ptb} -> generic.
    payload3 = _capture_webhook_call(
        engine, alert, "https://foo.discord.com/hook",
    )
    assert "embeds" not in payload3


@pytest.mark.parametrize("host", ["discord.com", "canary.discord.com", "ptb.discord.com"])
def test_webhook_discord_canonical_allowlist_accepts(host: str):
    """The three allowlisted Discord hosts must still be recognised."""
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine([rule])
    alert = Alert(
        rule_name="r", severity="info", message="hello",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata={},
    )
    payload = _capture_webhook_call(
        engine, alert, f"https://{host}/api/webhooks/1/abc",
    )
    assert "embeds" in payload
    assert "content" in payload


def test_email_starttls_structural_check_swallows_mock(monkeypatch):
    """Round V: a non-tuple STARTTLS return (e.g. MagicMock) must NOT
    raise. The structural check ``isinstance(ret, tuple) and ...`` lets
    the path proceed without the bogus ``(TypeError, ValueError)``
    bare-except that previously masked legitimate non-220 responses.
    """
    import smtplib
    monkeypatch.setenv("QFORGE_SMTP_PASSWORD", "x")
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com", smtp_port=587,
        smtp_user="u@example.com", smtp_to=["a@example.com"],
        smtp_password_env="QFORGE_SMTP_PASSWORD",
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fake_smtp = mock.MagicMock()
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    # MagicMock returns another MagicMock from .starttls(); NOT a tuple.
    with mock.patch.object(smtplib, "SMTP", return_value=cm):
        engine.send_email(alert)  # must not raise
    fake_smtp.starttls.assert_called_once()


def test_email_starttls_non_220_raises(monkeypatch):
    """Round V: a real ``(code, response)`` tuple where ``code != 220``
    must surface as a ``RuntimeError`` (not silently swallowed by the
    old broad ``except (TypeError, ValueError)``).
    """
    import smtplib
    monkeypatch.setenv("QFORGE_SMTP_PASSWORD", "x")
    rule = AlertRule(name="r", metric="m", threshold=0.0)
    engine = _make_engine(
        [rule],
        smtp_host="smtp.example.com", smtp_port=587,
        smtp_user="u@example.com", smtp_to=["a@example.com"],
        smtp_password_env="QFORGE_SMTP_PASSWORD",
    )
    alert = Alert(
        rule_name="r", severity="warn", message="x",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fake_smtp = mock.MagicMock()
    fake_smtp.starttls.return_value = (550, b"TLS not available")
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with mock.patch.object(smtplib, "SMTP", return_value=cm):
        with pytest.raises(RuntimeError, match="STARTTLS"):
            engine.send_email(alert)
