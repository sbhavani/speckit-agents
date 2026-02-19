"""Monitoring utilities for Redis Streams."""

import logging
from dataclasses import dataclass
from typing import Optional

import redis

from redis_streams.connection import RedisConnection

logger = logging.getLogger(__name__)


@dataclass
class BackpressureMetrics:
    """Backpressure metrics for a stream."""

    stream_length: int
    pending_count: int
    consumer_lag: int
    max_idle_time_ms: int
    is_healthy: bool
    warning: Optional[str] = None


class StreamMonitor:
    """Monitors stream health and backpressure."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize StreamMonitor.

        Args:
            redis_url: Redis connection URL
        """
        self._connection = RedisConnection(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def get_backpressure_metrics(
        self,
        stream: str,
        group: str,
    ) -> BackpressureMetrics:
        """Get backpressure metrics for a stream/group.

        Args:
            stream: Stream name
            group: Consumer group name

        Returns:
            BackpressureMetrics object
        """
        try:
            # Get stream length
            stream_length = self.client.xlen(stream)

            # Get pending info
            pending_info = self.client.xpending(stream, group, count=1)

            pending_count = pending_info.get("pending", 0)
            _min_idle = pending_info.get("min", 0)
            max_idle = pending_info.get("max", 0)

            # Calculate lag
            consumer_lag = pending_count

            # Determine health
            is_healthy = True
            warning = None

            if max_idle > 30000:  # 30 seconds
                is_healthy = False
                warning = f"Consumer lag detected: max idle time {max_idle}ms"
            elif consumer_lag > 1000:
                warning = f"High pending count: {consumer_lag} messages"

            return BackpressureMetrics(
                stream_length=stream_length,
                pending_count=pending_count,
                consumer_lag=consumer_lag,
                max_idle_time_ms=max_idle,
                is_healthy=is_healthy,
                warning=warning,
            )

        except Exception as e:
            logger.error(f"Failed to get backpressure metrics: {e}")
            return BackpressureMetrics(
                stream_length=0,
                pending_count=0,
                consumer_lag=0,
                max_idle_time_ms=0,
                is_healthy=False,
                warning=f"Failed to get metrics: {e}",
            )

    def check_stream_health(
        self,
        stream: str,
    ) -> bool:
        """Check if stream is healthy.

        Args:
            stream: Stream name

        Returns:
            True if stream exists and is accessible
        """
        try:
            return self.client.exists(stream) > 0
        except Exception:
            return False

    def get_stream_stats(
        self,
        stream: str,
    ) -> dict:
        """Get comprehensive stream statistics.

        Args:
            stream: Stream name

        Returns:
            Dict with stream stats
        """
        try:
            info = self.client.xinfo_stream(stream)
            return {
                "length": info.get("length", 0),
                "first_entry_id": info.get("first-entry-id"),
                "last_entry_id": info.get("last-entry-id"),
                "groups": info.get("groups", 0),
                "radix_tree_keys": info.get("radix-tree-keys", 0),
            }
        except Exception as e:
            logger.error(f"Failed to get stream stats: {e}")
            return {}

    def close(self):
        """Close connection."""
        self._connection.close()


class LagMonitor:
    """Monitors consumer lag over time."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize LagMonitor."""
        self._connection = RedisConnection(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def get_consumer_lag(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> int:
        """Get lag (pending messages) for a specific consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name

        Returns:
            Number of pending messages for this consumer
        """
        try:
            pending = self.client.xpending_ext(
                stream,
                group,
                start="-",
                end="+",
                count=100,
                consumer=consumer,
            )
            return len(pending)
        except Exception as e:
            logger.error(f"Failed to get consumer lag: {e}")
            return 0

    def get_all_consumer_lags(
        self,
        stream: str,
        group: str,
    ) -> dict:
        """Get lag for all consumers in a group.

        Args:
            stream: Stream name
            group: Consumer group name

        Returns:
            Dict mapping consumer name to lag count
        """
        lags = {}
        try:
            pending = self.client.xpending_ext(
                stream,
                group,
                start="-",
                end="+",
                count=1000,
            )

            for p in pending:
                consumer = p.get("consumer", "unknown")
                lags[consumer] = lags.get(consumer, 0) + 1

        except Exception as e:
            logger.error(f"Failed to get consumer lags: {e}")

        return lags

    def close(self):
        """Close connection."""
        self._connection.close()
