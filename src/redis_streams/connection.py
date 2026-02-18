"""Redis connection management with connection pooling."""

import time
import logging
from typing import Optional, Callable, Any, TypeVar
import redis
from redis.connection import ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)

T = TypeVar('T')


def with_retry(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        func: Function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff

    Returns:
        Result of func

    Raises:
        The last exception if all retries fail
    """
    last_exception = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            return func()
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"Redis operation failed after {max_retries + 1} attempts: {e}")

    raise last_exception


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
