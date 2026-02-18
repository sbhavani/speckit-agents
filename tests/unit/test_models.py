"""Unit tests for Redis Streams models."""

import pytest
from redis_streams.models import EventMessage, PendingMessage


class TestEventMessage:
    """Tests for EventMessage model."""

    def test_from_redis(self):
        """Test creating EventMessage from Redis format."""
        values = {
            "event_type": "price.update",
            "payload": '{"symbol": "AAPL", "price": 150.0}',
            "timestamp": "2024-01-01T00:00:00",
            "metadata": '{"source": "feed"}',
        }

        msg = EventMessage.from_redis("test_stream", "1234567890-0", values)

        assert msg.id == "1234567890-0"
        assert msg.stream == "test_stream"
        assert msg.event_type == "price.update"
        assert msg.payload == {"symbol": "AAPL", "price": 150.0}
        assert msg.timestamp == "2024-01-01T00:00:00"
        assert msg.metadata == {"source": "feed"}

    def test_to_dict(self):
        """Test converting EventMessage to dict."""
        msg = EventMessage(
            id="1234567890-0",
            stream="test_stream",
            event_type="test.event",
            payload={"key": "value"},
            timestamp="2024-01-01T00:00:00",
            metadata={"meta": "data"},
        )

        result = msg.to_dict()

        assert result["event_type"] == "test.event"
        assert result["payload"] == '{"key": "value"}'
        assert result["timestamp"] == "2024-01-01T00:00:00"
        assert result["metadata"] == '{"meta": "data"}'


class TestPendingMessage:
    """Tests for PendingMessage model."""

    def test_from_redis(self):
        """Test creating PendingMessage from Redis format."""
        pending = {
            "message_id": "1234567890-0",
            "consumer": "consumer-1",
            "time_since_delivered": 5000,
            "delivery_counter": 3,
        }

        msg = PendingMessage.from_redis("test_stream", "test_group", pending)

        assert msg.id == "1234567890-0"
        assert msg.consumer == "consumer-1"
        assert msg.idle_ms == 5000
        assert msg.delivered == 3
        assert msg.stream == "test_stream"
        assert msg.group == "test_group"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
