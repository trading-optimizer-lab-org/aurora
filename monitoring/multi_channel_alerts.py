"""Multi-channel alerts (R122).

Extends `monitoring/alerts.py` with SMS (Twilio), push (Pushover /
Pushbullet) and Telegram. Per-event channel routing so the kill-switch
fires SMS while the daily summary lands on Slack.

Each provider is a thin wrapper that delegates to a caller-supplied
HTTP client; the goal is to avoid hard dependencies at import time.
Real wiring happens at operator-side configuration, not here.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger("aurora.monitoring.multi_channel_alerts")


# --------------------------------------------------------------------------
# Provider protocol
# --------------------------------------------------------------------------


@dataclass
class AlertEvent:
    """Common alert envelope across channels."""

    title: str
    body: str
    severity: str = "info"  # info | warn | error | critical
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


class SMSProvider:
    """Twilio SMS sender. Lazy import so no hard dep at import time."""

    name = "twilio_sms"

    def __init__(
        self,
        account_sid_env: str = "TWILIO_ACCOUNT_SID",
        auth_token_env: str = "TWILIO_AUTH_TOKEN",
        from_number_env: str = "TWILIO_FROM_NUMBER",
        to_number_env: str = "TWILIO_TO_NUMBER",
    ) -> None:
        self.account_sid_env = account_sid_env
        self.auth_token_env = auth_token_env
        self.from_number_env = from_number_env
        self.to_number_env = to_number_env

    def send(self, event: AlertEvent) -> Dict[str, Any]:
        sid = os.environ.get(self.account_sid_env, "")
        token = os.environ.get(self.auth_token_env, "")
        from_n = os.environ.get(self.from_number_env, "")
        to_n = os.environ.get(self.to_number_env, "")
        if not (sid and token and from_n and to_n):
            return {"ok": False, "error": "twilio env vars not set"}
        try:
            from twilio.rest import Client
        except ImportError:
            return {"ok": False, "error": "twilio package not installed"}
        client = Client(sid, token)
        message = client.messages.create(
            body=f"[{event.severity.upper()}] {event.title}\n{event.body}"[:1600],
            from_=from_n,
            to=to_n,
        )
        return {"ok": True, "sid": message.sid}


class PushoverProvider:
    """Pushover.net push notification."""

    name = "pushover"

    def __init__(
        self,
        token_env: str = "PUSHOVER_TOKEN",
        user_env: str = "PUSHOVER_USER",
        http_post: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.token_env = token_env
        self.user_env = user_env
        self._http_post = http_post

    def send(self, event: AlertEvent) -> Dict[str, Any]:
        token = os.environ.get(self.token_env, "")
        user = os.environ.get(self.user_env, "")
        if not (token and user):
            return {"ok": False, "error": "pushover env vars not set"}
        post = self._http_post
        if post is None:
            try:
                import requests
                post = requests.post
            except ImportError:
                return {"ok": False, "error": "requests package not installed"}
        priority = {"info": -1, "warn": 0, "error": 1, "critical": 2}.get(
            event.severity.lower(), 0
        )
        try:
            r = post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": token,
                    "user": user,
                    "title": event.title,
                    "message": event.body,
                    "priority": priority,
                },
                timeout=10,
            )
            return {"ok": getattr(r, "ok", True), "status_code": getattr(r, "status_code", None)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


class TelegramProvider:
    """Telegram bot push."""

    name = "telegram"

    def __init__(
        self,
        bot_token_env: str = "TELEGRAM_BOT_TOKEN",
        chat_id_env: str = "TELEGRAM_CHAT_ID",
        http_post: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.bot_token_env = bot_token_env
        self.chat_id_env = chat_id_env
        self._http_post = http_post

    def send(self, event: AlertEvent) -> Dict[str, Any]:
        token = os.environ.get(self.bot_token_env, "")
        chat = os.environ.get(self.chat_id_env, "")
        if not (token and chat):
            return {"ok": False, "error": "telegram env vars not set"}
        post = self._http_post
        if post is None:
            try:
                import requests
                post = requests.post
            except ImportError:
                return {"ok": False, "error": "requests package not installed"}
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = post(
                url,
                json={
                    "chat_id": chat,
                    "text": f"*{event.title}*\n{event.body}",
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            return {"ok": getattr(r, "ok", True), "status_code": getattr(r, "status_code", None)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Multi-channel router
# --------------------------------------------------------------------------


@dataclass
class ChannelRoute:
    """Per-severity channel routing."""

    severity: str
    providers: List[Any]


class MultiChannelAlerter:
    """Route alerts to one or more provider lists by severity."""

    def __init__(self, routes: List[ChannelRoute]) -> None:
        self._routes = {r.severity: r.providers for r in routes}

    def send(self, event: AlertEvent) -> List[Dict[str, Any]]:
        providers = self._routes.get(event.severity, [])
        results: List[Dict[str, Any]] = []
        for p in providers:
            try:
                results.append({
                    "provider": getattr(p, "name", str(p)),
                    "result": p.send(event),
                })
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "provider": getattr(p, "name", str(p)),
                    "result": {"ok": False, "error": str(exc)},
                })
        return results


__all__ = [
    "AlertEvent",
    "SMSProvider",
    "PushoverProvider",
    "TelegramProvider",
    "ChannelRoute",
    "MultiChannelAlerter",
]
