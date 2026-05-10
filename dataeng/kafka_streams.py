"""Kafka producer/consumer wrapper with lazy ``confluent-kafka`` import.

In ``mock=True`` mode events are stored in an in-process deque so tests can
publish and consume without a real broker.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class KafkaConfig:
    """Static config for :class:`KafkaEventStream`.

    Attributes:
        bootstrap_servers: comma-separated broker list.
        topic: default topic for publish/consume.
        group_id: consumer group id.
        client_id: client id for producer/consumer.
        max_buffer: in-memory buffer size in mock mode.
    """
    bootstrap_servers: str = "localhost:9092"
    topic: str = "aurora.events"
    group_id: str = "quantforge"
    client_id: str = "quantforge-client"
    max_buffer: int = 10_000


class KafkaEventStream:
    """Lightweight producer/consumer facade."""

    def __init__(self, config: Optional[KafkaConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or KafkaConfig()
        self.mock = bool(mock)
        self._buffer: deque = deque(maxlen=self.config.max_buffer)
        self._producer: Any = None
        self._consumer: Any = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def publish(self, event: dict, topic: Optional[str] = None) -> bool:
        """Publish a JSON-serializable event. Returns True on success."""
        topic = topic or self.config.topic
        payload = json.dumps(event, default=str)
        if self.mock:
            self._buffer.append({"topic": topic, "payload": payload})
            return True
        return self._producer_send(topic, payload)  # pragma: no cover

    def consume(self, max_events: int = 100,
                timeout_s: float = 1.0) -> list[dict]:
        """Consume up to ``max_events`` events. Returns parsed payloads."""
        if self.mock:
            out = []
            for _ in range(min(max_events, len(self._buffer))):
                rec = self._buffer.popleft()
                try:
                    out.append(json.loads(rec["payload"]))
                except json.JSONDecodeError:
                    continue
            return out
        return self._consumer_poll(max_events, timeout_s)  # pragma: no cover

    def buffer_size(self) -> int:
        return len(self._buffer)

    def flush(self) -> None:
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Internals (real broker paths)
    # ------------------------------------------------------------------
    def _producer_send(self, topic: str, payload: str) -> bool:  # pragma: no cover
        try:
            from confluent_kafka import Producer
        except ImportError as e:
            raise ImportError("confluent-kafka required for live mode") from e
        if self._producer is None:
            self._producer = Producer({
                "bootstrap.servers": self.config.bootstrap_servers,
                "client.id": self.config.client_id,
            })
        self._producer.produce(topic, payload.encode("utf-8"))
        self._producer.flush()
        return True

    def _consumer_poll(self, max_events: int,
                       timeout_s: float) -> list[dict]:  # pragma: no cover
        try:
            from confluent_kafka import Consumer
        except ImportError as e:
            raise ImportError("confluent-kafka required for live mode") from e
        if self._consumer is None:
            self._consumer = Consumer({
                "bootstrap.servers": self.config.bootstrap_servers,
                "group.id": self.config.group_id,
                "auto.offset.reset": "earliest",
            })
            self._consumer.subscribe([self.config.topic])
        out = []
        for _ in range(max_events):
            msg = self._consumer.poll(timeout=timeout_s)
            if msg is None or msg.error():
                continue
            try:
                out.append(json.loads(msg.value().decode("utf-8")))
            except json.JSONDecodeError:
                continue
        return out
