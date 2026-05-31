"""Tests for aurora.dataeng.kafka_streams."""
from __future__ import annotations

import pytest

from aurora.dataeng.kafka_streams import KafkaConfig, KafkaEventStream


@pytest.fixture
def stream() -> KafkaEventStream:
    return KafkaEventStream(KafkaConfig(topic="test.topic"), mock=True)


def test_publish_increments_buffer(stream: KafkaEventStream):
    assert stream.buffer_size() == 0
    stream.publish({"id": 1, "v": "a"})
    stream.publish({"id": 2, "v": "b"})
    assert stream.buffer_size() == 2


def test_consume_returns_published_events(stream: KafkaEventStream):
    stream.publish({"id": 1})
    stream.publish({"id": 2})
    out = stream.consume(max_events=10)
    assert [e["id"] for e in out] == [1, 2]
    assert stream.buffer_size() == 0


def test_consume_respects_max_events(stream: KafkaEventStream):
    for i in range(5):
        stream.publish({"i": i})
    out = stream.consume(max_events=2)
    assert len(out) == 2
    assert stream.buffer_size() == 3


def test_flush_clears_buffer(stream: KafkaEventStream):
    stream.publish({"x": 1})
    stream.flush()
    assert stream.buffer_size() == 0
    assert stream.consume() == []


def test_publish_returns_true_in_mock(stream: KafkaEventStream):
    assert stream.publish({"any": "event"}) is True
