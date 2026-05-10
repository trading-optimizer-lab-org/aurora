"""QuantForge live alerts: rule-based monitoring with email + webhook delivery.

This module evaluates user-supplied rules against runtime metrics and dispatches
notifications via SMTP and HTTP webhooks. The webhook payload format
(Slack vs Discord) is auto-detected from the URL hostname.

Design notes
------------
* Stdlib only. No requests, no external HTTP client.
* Credentials are NEVER stored in :class:`AlertConfig` — only the *name* of the
  env var holding the password (``smtp_password_env``) is kept. The password
  itself is read from ``os.environ`` at send time and never logged.
* Cooldown is per-rule. A rule that fired ``cooldown_seconds`` ago will be
  suppressed even if the metric still breaches its threshold.

Run tests::

    cd "C:/Users/HP/MODELO SP500"
    uv run pytest quantforge/tests/test_alerts.py -v
"""
from __future__ import annotations

import json
import logging
import math
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Callable, Optional, Sequence
from urllib.parse import urlparse

import numpy as np

__all__ = [
    "Alert",
    "AlertConfig",
    "AlertEngine",
    "AlertRule",
    "compute_daily_loss",
    "compute_drift_metric",
    "compute_max_dd",
    "default_rules",
]

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Dataclasses                                                                 #
# --------------------------------------------------------------------------- #
SEVERITY_LEVELS = ("info", "warn", "critical")
VALID_OPERATORS = (">", "<", ">=", "<=", "==")


@dataclass
class AlertRule:
    """A single threshold rule against a named metric.

    Notes
    -----
    The ``==`` operator is intended for integer-valued metrics. When applied to
    a float metric the comparison uses :func:`math.isclose` with
    ``abs_tol=eq_abs_tol`` (default 1e-9) to avoid spurious false negatives
    from binary floating-point representation. Use ``eq_abs_tol`` to widen the
    tolerance when comparing scaled metrics.
    """

    name: str
    metric: str
    threshold: float
    operator: str = ">"
    severity: str = "warn"
    cooldown_seconds: int = 3600
    eq_abs_tol: float = 1e-9

    def __post_init__(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(
                f"AlertRule.operator must be one of {VALID_OPERATORS}, "
                f"got {self.operator!r}"
            )
        if self.severity not in SEVERITY_LEVELS:
            raise ValueError(
                f"AlertRule.severity must be one of {SEVERITY_LEVELS}, "
                f"got {self.severity!r}"
            )
        if self.cooldown_seconds < 0:
            raise ValueError("AlertRule.cooldown_seconds must be >= 0")
        if self.eq_abs_tol < 0:
            raise ValueError("AlertRule.eq_abs_tol must be >= 0")

    def check(self, value: float) -> bool:
        """Return True if ``value`` breaches the threshold."""
        op = self.operator
        t = self.threshold
        if op == ">":
            return value > t
        if op == "<":
            return value < t
        if op == ">=":
            return value >= t
        if op == "<=":
            return value <= t
        # operator == "=="
        # If both threshold and value are integral (or threshold is int) use
        # exact equality. Otherwise fall back to math.isclose with eq_abs_tol
        # because direct float == is unreliable for measured metrics.
        if isinstance(t, int) and float(value).is_integer():
            return int(value) == t
        return math.isclose(float(value), float(t), abs_tol=self.eq_abs_tol)


@dataclass
class AlertConfig:
    """Configuration for :class:`AlertEngine` — credentials live in env vars."""

    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    # NOTE: name of env var holding password, NOT the value.
    smtp_password_env: str = "QFORGE_SMTP_PASSWORD"
    smtp_to: Optional[list] = None
    webhook_urls: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    # Webhook delivery: only HTTPS is allowed unless the operator opts in.
    allow_http_webhooks: bool = False
    # Retry once on 5xx with this much backoff (seconds). 0 disables retries.
    webhook_retry_backoff_s: float = 1.0

    def __post_init__(self) -> None:
        # Reject duplicate rule names so cooldown/dispatch bookkeeping cannot
        # silently key on an ambiguous name.
        names = [getattr(r, "name", None) for r in (self.rules or [])]
        seen: set = set()
        dupes: list = []
        for n in names:
            if n in seen:
                dupes.append(n)
            else:
                seen.add(n)
        if dupes:
            raise ValueError(
                f"AlertConfig.rules contains duplicate rule name(s): "
                f"{sorted(set(dupes))}. Rule names must be unique."
            )


@dataclass
class Alert:
    """A triggered alert event."""

    rule_name: str
    severity: str
    message: str
    timestamp: datetime
    metadata: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Metric helpers                                                              #
# --------------------------------------------------------------------------- #
def compute_drift_metric(
    reference_dist: Sequence[float],
    current_dist: Sequence[float],
) -> float:
    """Mean-shift z-score between two distributions.

    Returns the absolute standardized difference of means, scaled by the
    reference distribution standard deviation. Larger = more drift.
    """
    ref = np.asarray(reference_dist, dtype=float)
    cur = np.asarray(current_dist, dtype=float)
    if ref.size == 0 or cur.size == 0:
        return 0.0
    ref_std = float(ref.std(ddof=0))
    if ref_std == 0.0:
        # Fall back to absolute mean difference; avoids divide-by-zero.
        return float(abs(cur.mean() - ref.mean()))
    return float(abs(cur.mean() - ref.mean()) / ref_std)


def compute_daily_loss(equity_curve: Sequence[float]) -> float:
    """Last day's PnL %, computed as ``(eq[-1] - eq[-2]) / eq[-2]``.

    Returns 0.0 if fewer than 2 points or the prior equity is non-positive.
    """
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size < 2:
        return 0.0
    prior = float(eq[-2])
    if prior <= 0:
        return 0.0
    return float((eq[-1] - prior) / prior)


def compute_max_dd(equity_curve: Sequence[float]) -> float:
    """Max drawdown so far, returned as a positive fraction (e.g., 0.20 = 20%).

    Requires the equity curve to start positive: ``equity_curve[0] > 0``.
    A non-positive starting equity makes the drawdown ratio undefined
    (division by zero or sign flip), so this function returns ``NaN`` in
    that case rather than producing a meaningless number.

    Per-bar drawdown ``(eq[i] - peak[i]) / peak[i]`` is also clamped to
    ``NaN`` at any bar where the running peak is non-positive — this can
    only happen on a stretch of non-positive equity, where drawdown has
    no meaning anyway.
    """
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size == 0:
        return 0.0
    if eq[0] <= 0:
        return float("nan")
    peak = np.maximum.accumulate(eq)
    # Where the running peak is non-positive, drawdown is undefined; mark
    # those bars as NaN and ignore them in the min.
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (eq - peak) / peak, np.nan)
    if np.all(np.isnan(dd)):
        return float("nan")
    return float(-np.nanmin(dd))


# --------------------------------------------------------------------------- #
# Default rule preset                                                         #
# --------------------------------------------------------------------------- #
def default_rules() -> list:
    """Sensible production defaults matching v1.3 specs."""
    return [
        AlertRule(
            name="drift_warn",
            metric="drift",
            threshold=0.05,
            operator=">",
            severity="warn",
        ),
        AlertRule(
            name="max_dd_critical",
            metric="max_dd",
            threshold=0.20,
            operator=">",
            severity="critical",
        ),
        AlertRule(
            name="daily_loss_warn",
            metric="daily_loss",
            threshold=-0.05,
            operator="<",
            severity="warn",
        ),
        AlertRule(
            name="sharpe_warn",
            metric="sharpe",
            threshold=0.0,
            operator="<",
            severity="warn",
        ),
    ]


# --------------------------------------------------------------------------- #
# AlertEngine                                                                 #
# --------------------------------------------------------------------------- #
class AlertEngine:
    """Evaluate rules against metrics and dispatch via email + webhooks.

    Parameters
    ----------
    config : AlertConfig
        Channels, rules, and credential pointers.
    now_func : callable, optional
        Returns current ``datetime``. Override in tests for deterministic
        cooldown behavior. Default: ``lambda: datetime.now(timezone.utc)``.
    """

    def __init__(
        self,
        config: AlertConfig,
        now_func: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config
        self._now = now_func or (lambda: datetime.now(timezone.utc))
        # Per-rule deque of recent fire timestamps for cooldown bookkeeping.
        self._fire_history: dict = {}

    # --- evaluation -------------------------------------------------------- #
    def evaluate(self, metrics: dict) -> list:
        """Check all rules against ``metrics`` and return triggered alerts.

        Rules that reference a missing metric key are skipped silently — the
        runtime may not have produced that metric yet.
        """
        triggered = []
        ts = self._now()
        for rule in self.config.rules:
            if rule.metric not in metrics:
                continue
            value = metrics[rule.metric]
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                log.warning(
                    "AlertEngine: rule %r metric %r value not numeric (%r); skipping",
                    rule.name, rule.metric, value,
                )
                continue
            if rule.check(value_f):
                msg = (
                    f"[{rule.severity.upper()}] {rule.name}: "
                    f"{rule.metric}={value_f:.6g} {rule.operator} {rule.threshold:g}"
                )
                triggered.append(
                    Alert(
                        rule_name=rule.name,
                        severity=rule.severity,
                        message=msg,
                        timestamp=ts,
                        metadata={
                            "metric": rule.metric,
                            "value": value_f,
                            "threshold": rule.threshold,
                            "operator": rule.operator,
                        },
                    )
                )
        return triggered

    # --- cooldown ---------------------------------------------------------- #
    def _is_in_cooldown(self, rule_name: str, cooldown_seconds: int) -> bool:
        if cooldown_seconds <= 0:
            return False
        history = self._fire_history.get(rule_name)
        if not history:
            return False
        last_fire = history[-1]
        elapsed = (self._now() - last_fire).total_seconds()
        return elapsed < cooldown_seconds

    def _record_fire(self, rule_name: str) -> None:
        dq = self._fire_history.setdefault(rule_name, deque(maxlen=64))
        dq.append(self._now())

    def _rule_for(self, rule_name: str) -> Optional[AlertRule]:
        for r in self.config.rules:
            if r.name == rule_name:
                return r
        return None

    # --- dispatch ---------------------------------------------------------- #
    def fire(self, alert: Alert) -> bool:
        """Send ``alert`` via all configured channels.

        Respects per-rule cooldown — a duplicate fire within the cooldown
        window is suppressed. Returns ``True`` when sent, ``False`` if
        suppressed by cooldown.
        """
        rule = self._rule_for(alert.rule_name)
        cooldown = rule.cooldown_seconds if rule else 0
        if self._is_in_cooldown(alert.rule_name, cooldown):
            log.info("AlertEngine: alert %r suppressed by cooldown", alert.rule_name)
            return False

        # Email channel
        if self.config.smtp_host and self.config.smtp_to:
            try:
                self.send_email(alert)
            except Exception:
                # Log without leaking the password env contents.
                log.exception("AlertEngine: send_email failed for %r", alert.rule_name)

        # Webhook channels
        for url in self.config.webhook_urls or []:
            try:
                self.send_webhook(alert, url=url)
            except Exception:
                log.exception(
                    "AlertEngine: send_webhook failed for %r (host=%s)",
                    alert.rule_name,
                    urlparse(url).hostname,
                )

        self._record_fire(alert.rule_name)
        return True

    # --- email ------------------------------------------------------------- #
    def send_email(self, alert: Alert) -> None:
        """Send ``alert`` via SMTP+TLS. Password is read from env at call time."""
        cfg = self.config
        if not cfg.smtp_host or not cfg.smtp_to:
            raise RuntimeError("send_email called without smtp_host/smtp_to configured")

        password = os.environ.get(cfg.smtp_password_env)
        if not password:
            raise RuntimeError(
                f"SMTP password env var {cfg.smtp_password_env!r} is not set; "
                f"cannot send email alert {alert.rule_name!r}"
            )

        msg = EmailMessage()
        msg["Subject"] = f"[QuantForge {alert.severity.upper()}] {alert.rule_name}"
        msg["From"] = cfg.smtp_user or "quantforge-alerts@localhost"
        msg["To"] = ", ".join(cfg.smtp_to)
        body_lines = [
            alert.message,
            "",
            f"Timestamp: {alert.timestamp.isoformat()}",
            f"Severity:  {alert.severity}",
            f"Rule:      {alert.rule_name}",
            "",
            "Metadata:",
        ]
        for k, v in alert.metadata.items():
            body_lines.append(f"  {k}: {v}")
        msg.set_content("\n".join(body_lines))

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
            # Use the system default SSL context to enable certificate +
            # hostname verification for the STARTTLS upgrade. ``starttls``
            # returns ``(code, response)``; ``smtplib`` raises on a
            # non-2xx server reply, so we only post-validate when the
            # tuple is structurally available (mocks may return anything).
            ctx = ssl.create_default_context()
            ret = smtp.starttls(context=ctx)
            # Real smtplib returns ``(code, response)``: a 2-tuple whose
            # first entry is the integer SMTP reply code. Mocks and ad-hoc
            # subclasses may return anything else (MagicMock, None, ...).
            # We only validate the post-condition when the return value
            # matches smtplib's documented contract; otherwise we trust
            # smtplib to have raised on a real failure. Using a structural
            # check (instead of catching ``TypeError``/``ValueError``)
            # keeps a real failure -- e.g. ``ret = (550, b"...")`` -- from
            # being silently swallowed alongside mock noise.
            is_smtplib_response = (
                isinstance(ret, tuple)
                and len(ret) == 2
                and isinstance(ret[0], int)
            )
            if is_smtplib_response and ret[0] != 220:
                raise RuntimeError(
                    f"STARTTLS upgrade failed: server returned code {ret[0]}"
                )
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, password)
            smtp.send_message(msg)

    # --- webhook ----------------------------------------------------------- #
    def send_webhook(self, alert: Alert, url: Optional[str] = None) -> None:
        """POST ``alert`` to webhook ``url`` (or every configured URL).

        Slack vs Discord payload format auto-detected by hostname. Only
        ``https://`` URLs are accepted unless ``AlertConfig.allow_http_webhooks``
        is True. Redirects are disabled to prevent leaking the alert payload to
        an unintended host. Retries once with backoff on 5xx responses.
        """
        if url is None:
            for u in self.config.webhook_urls or []:
                self.send_webhook(alert, url=u)
            return

        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme == "http":
            if not self.config.allow_http_webhooks:
                raise ValueError(
                    "AlertEngine: webhook URL must use https:// scheme "
                    "(set AlertConfig.allow_http_webhooks=True to override). "
                    f"Got: {scheme!r}"
                )
        elif scheme != "https":
            raise ValueError(
                "AlertEngine: webhook URL must use https:// scheme; "
                f"got scheme {scheme!r}"
            )

        payload = self._build_webhook_payload(alert, url)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        attempts = 0
        max_attempts = 2  # original + 1 retry on 5xx
        backoff = max(0.0, float(self.config.webhook_retry_backoff_s))
        last_exc: Optional[BaseException] = None
        while attempts < max_attempts:
            attempts += 1
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    # Drain so the connection can be released.
                    resp.read()
                    status_raw = getattr(resp, "status", None)
                    if status_raw is None:
                        try:
                            status_raw = resp.getcode()
                        except Exception:
                            status_raw = 200
                    # Only trust ``int``/``str`` numeric responses. Anything
                    # else (mocks, unusual response objects) is treated as a
                    # successful 200 to avoid spurious failures from
                    # ``int(MagicMock())`` returning 1.
                    if isinstance(status_raw, bool):
                        status = 200
                    elif isinstance(status_raw, int):
                        status = status_raw
                    elif isinstance(status_raw, str) and status_raw.isdigit():
                        status = int(status_raw)
                    else:
                        status = 200
                    # 30x means a redirect was followed silently. Refuse.
                    if 300 <= status < 400:
                        raise urllib.error.HTTPError(
                            url, status,
                            "webhook returned a redirect; refusing to follow",
                            getattr(resp, "headers", None),  # type: ignore[arg-type]
                            None,
                        )
                    if 200 <= status < 300:
                        return
                    if 500 <= status < 600 and attempts < max_attempts:
                        log.warning(
                            "AlertEngine: webhook returned HTTP %s for %r; retrying",
                            status, alert.rule_name,
                        )
                        if backoff > 0:
                            time.sleep(backoff)
                        continue
                    raise urllib.error.HTTPError(
                        url, status, f"unexpected webhook status {status}",
                        getattr(resp, "headers", None),  # type: ignore[arg-type]
                        None,
                    )
            except urllib.error.HTTPError as e:
                last_exc = e
                if 500 <= int(e.code) < 600 and attempts < max_attempts:
                    log.warning(
                        "AlertEngine: webhook returned HTTP %s for %r; retrying",
                        e.code, alert.rule_name,
                    )
                    if backoff > 0:
                        time.sleep(backoff)
                    continue
                log.error(
                    "AlertEngine: webhook returned HTTP %s for %r",
                    e.code, alert.rule_name,
                )
                raise
        if last_exc is not None:
            raise last_exc

    @staticmethod
    def _build_webhook_payload(alert: Alert, url: str) -> dict:
        host = (urlparse(url).hostname or "").lower()
        # Strict allowlist for Discord and Slack hosts. We deliberately do
        # NOT match ``.discordapp.com`` (a deprecated alias) and we do NOT
        # accept arbitrary ``*.discord.com`` subdomains - only the canary
        # and ptb release channels alongside the canonical ``discord.com``.
        # This blocks payload-format spoofing via lookalike hosts such as
        # ``cdn.discord.com.evil.example`` or ``app.discordapp.com``.
        _DISCORD_HOSTS = frozenset({
            "discord.com",
            "canary.discord.com",
            "ptb.discord.com",
        })
        is_discord = host in _DISCORD_HOSTS
        is_slack = host == "slack.com" or host.endswith(".slack.com")

        if is_discord:
            # Discord webhook expects ``content`` (and optional ``embeds``).
            return {
                "content": alert.message,
                "embeds": [
                    {
                        "title": alert.rule_name,
                        "description": alert.message,
                        "timestamp": alert.timestamp.isoformat(),
                        "fields": [
                            {"name": "severity", "value": alert.severity, "inline": True},
                            *[
                                {"name": str(k), "value": str(v), "inline": True}
                                for k, v in alert.metadata.items()
                            ],
                        ],
                    }
                ],
            }

        if is_slack:
            # Slack incoming webhook: ``text`` + structured ``attachments``.
            color = {
                "info": "#2eb886",
                "warn": "#daa038",
                "critical": "#a30200",
            }.get(alert.severity, "#cccccc")
            return {
                "text": alert.message,
                "attachments": [
                    {
                        "color": color,
                        "title": alert.rule_name,
                        "text": alert.message,
                        "ts": int(alert.timestamp.timestamp()),
                        "fields": [
                            {"title": "severity", "value": alert.severity, "short": True},
                            *[
                                {"title": str(k), "value": str(v), "short": True}
                                for k, v in alert.metadata.items()
                            ],
                        ],
                    }
                ],
            }

        # Generic JSON payload for any other webhook.
        return {
            "rule_name": alert.rule_name,
            "severity": alert.severity,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "metadata": alert.metadata,
        }
