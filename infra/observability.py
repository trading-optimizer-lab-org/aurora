"""Prometheus metrics + Grafana dashboard JSON emitter.

Lazy ``prometheus_client``. When the SDK is missing, counters fall back
to an in-memory dict so callers can still increment metrics. The
``render_grafana_dashboard`` helper produces a Grafana dashboard JSON
that references the standard Prometheus counters this module ships.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


_DEFAULT_COUNTERS: tuple[tuple[str, str], ...] = (
    ("orders_total", "Total orders submitted"),
    ("rejections_total", "Total order rejections"),
    ("fills_total", "Total order fills"),
)
_DEFAULT_GAUGES: tuple[tuple[str, str], ...] = (
    ("pnl_total", "Cumulative realized PnL"),
    ("position_size", "Current position size (signed)"),
    ("cash_balance", "Available cash balance"),
)


@dataclass
class ObservabilityConfig:
    """Static config for :class:`Observability`.

    Attributes:
        namespace: Prometheus metric namespace prefix.
        port: HTTP port for the Prometheus exposition endpoint.
        push_gateway: optional pushgateway URL (no test coverage).
        labels: default label key/values applied to every metric.
    """
    namespace: str = "quantforge"
    port: int = 9100
    push_gateway: str = ""
    labels: dict = field(default_factory=dict)


class Observability:
    """Prometheus emitter + Grafana dashboard generator."""

    def __init__(self, config: Optional[ObservabilityConfig] = None) -> None:
        self.config = config or ObservabilityConfig()
        self._lock = threading.Lock()
        # Mock store: counters keyed by (metric_name, labels_tuple) -> float.
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._client_counters: dict[str, Any] = {}
        self._client_gauges: dict[str, Any] = {}
        self._http_started = False
        self._init_client_metrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def inc_counter(self, name: str, value: float = 1.0,
                    labels: Optional[dict] = None) -> None:
        """Increment counter ``name``."""
        labels_t = self._labels_tuple(labels)
        with self._lock:
            key = (name, labels_t)
            self._counters[key] = self._counters.get(key, 0.0) + float(value)
        client = self._client_counters.get(name)
        if client is not None:  # pragma: no cover - prometheus path
            self._apply_labels(client, dict(labels_t)).inc(value)

    def set_gauge(self, name: str, value: float,
                  labels: Optional[dict] = None) -> None:
        """Set gauge ``name`` to ``value``."""
        labels_t = self._labels_tuple(labels)
        with self._lock:
            self._gauges[(name, labels_t)] = float(value)
        client = self._client_gauges.get(name)
        if client is not None:  # pragma: no cover - prometheus path
            self._apply_labels(client, dict(labels_t)).set(value)

    def get_counter(self, name: str, labels: Optional[dict] = None) -> float:
        """Read the in-memory counter value for ``name``."""
        labels_t = self._labels_tuple(labels)
        with self._lock:
            return float(self._counters.get((name, labels_t), 0.0))

    def get_gauge(self, name: str, labels: Optional[dict] = None) -> float:
        """Read the in-memory gauge value for ``name``."""
        labels_t = self._labels_tuple(labels)
        with self._lock:
            return float(self._gauges.get((name, labels_t), 0.0))

    def snapshot(self) -> dict:
        """Snapshot of every counter and gauge for /metrics-style export."""
        with self._lock:
            return {
                "counters": {
                    self._fmt_key(name, labels): v
                    for (name, labels), v in self._counters.items()
                },
                "gauges": {
                    self._fmt_key(name, labels): v
                    for (name, labels), v in self._gauges.items()
                },
            }

    def start_http_server(self, port: Optional[int] = None) -> bool:  # pragma: no cover
        """Start the prometheus_client HTTP server. No-op when SDK missing."""
        try:
            from prometheus_client import start_http_server
        except ImportError:
            return False
        if self._http_started:
            return True
        start_http_server(port if port is not None else self.config.port)
        self._http_started = True
        return True

    def render_grafana_dashboard(self, title: str = "QuantForge") -> dict:
        """Return a Grafana dashboard JSON dict with the default panels."""
        panels = []
        for i, (name, _) in enumerate(_DEFAULT_COUNTERS):
            panels.append({
                "id": i + 1,
                "title": name,
                "type": "stat",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "targets": [{
                    "expr": f"sum(rate({self.config.namespace}_{name}[5m]))",
                    "refId": chr(ord("A") + i),
                }],
                "gridPos": {"x": (i % 2) * 12, "y": (i // 2) * 8,
                            "w": 12, "h": 8},
            })
        offset = len(_DEFAULT_COUNTERS)
        for i, (name, _) in enumerate(_DEFAULT_GAUGES):
            panels.append({
                "id": offset + i + 1,
                "title": name,
                "type": "timeseries",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "targets": [{
                    "expr": f"{self.config.namespace}_{name}",
                    "refId": chr(ord("A") + i),
                }],
                "gridPos": {"x": (i % 2) * 12, "y": ((offset + i) // 2) * 8,
                            "w": 12, "h": 8},
            })
        return {
            "title": title,
            "uid": f"{self.config.namespace}-overview",
            "schemaVersion": 38,
            "version": 1,
            "panels": panels,
            "time": {"from": "now-6h", "to": "now"},
            "refresh": "30s",
            "tags": ["quantforge", "trading"],
        }

    def write_grafana_dashboard(self, path: str,
                                title: str = "QuantForge") -> str:
        """Persist the Grafana dashboard JSON to ``path``."""
        import os

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.render_grafana_dashboard(title), f, indent=2)
        return path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _labels_tuple(self, labels: Optional[dict]) -> tuple[tuple[str, str], ...]:
        merged = dict(self.config.labels or {})
        if labels:
            merged.update({str(k): str(v) for k, v in labels.items()})
        return tuple(sorted(merged.items()))

    @staticmethod
    def _fmt_key(name: str, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return name
        body = ",".join(f"{k}={v}" for k, v in labels)
        return f"{name}{{{body}}}"

    def _init_client_metrics(self) -> None:
        """Best-effort prometheus_client metric registration."""
        try:
            from prometheus_client import (
                Counter, Gauge,
            )
        except ImportError:
            return
        for name, doc in _DEFAULT_COUNTERS:
            try:  # pragma: no cover - prometheus path
                self._client_counters[name] = Counter(
                    f"{self.config.namespace}_{name}", doc,
                    list((self.config.labels or {}).keys()),
                )
            except Exception:  # noqa: BLE001 - already-registered etc.
                pass
        for name, doc in _DEFAULT_GAUGES:
            try:  # pragma: no cover - prometheus path
                self._client_gauges[name] = Gauge(
                    f"{self.config.namespace}_{name}", doc,
                    list((self.config.labels or {}).keys()),
                )
            except Exception:  # noqa: BLE001 - already-registered etc.
                pass

    @staticmethod
    def _apply_labels(metric: Any, labels: dict) -> Any:  # pragma: no cover
        if not labels:
            return metric
        try:
            return metric.labels(**labels)
        except Exception:  # noqa: BLE001 - mismatched label set
            return metric
