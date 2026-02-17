"""Redis connection management with connection pooling."""

from typing import Optional
import redis
from redis.connection import ConnectionPool


class RedisConnection:
    """Manages Redis connections with pooling."""

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        max_connections: int = 10,
        decode_responses: bool = True,
    ):
        """Initialize Redis connection.

        Args:
            url: Redis connection URL
            max_connections: Maximum connections in pool
            decode_responses: Whether to decode responses to strings
        """
        self.url = url
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._max_connections = max_connections
        self._decode_responses = decode_responses

    def connect(self) -> redis.Redis:
        """Create and return a Redis client."""
        if self._pool is None:
            self._pool = ConnectionPool.from_url(
                self.url,
                max_connections=self._max_connections,
                decode_responses=self._decode_responses,
            )
        if self._client is None:
            self._client = redis.Redis(connection_pool=self._pool)
        return self._client

    @property
    def client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            return self.connect()
        return self._client

    def ping(self) -> bool:
        """Check if Redis is available."""
        try:
            return self.client.ping()
        except redis.ConnectionError:
            return False

    def close(self):
        """Close connection pool."""
        if self._client:
            self._client.close()
            self._client = None
        if self._pool:
            self._pool.disconnect()
            self._pool = None

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Default connection instance
_default_connection: Optional[RedisConnection] = None


def get_default_connection(url: str = "redis://localhost:6379") -> RedisConnection:
    """Get or create default Redis connection."""
    global _default_connection
    if _default_connection is None:
        _default_connection = RedisConnection(url)
    return _default_connection


def set_default_connection(connection: RedisConnection):
    """Set default connection."""
    global _default_connection
    _default_connection = connection
