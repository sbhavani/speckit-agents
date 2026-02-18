"""Redis connection management with connection pooling."""

import logging
import time
from typing import Optional, Callable, TypeVar, Any
import redis
from redis.connection import ConnectionPool

logger = logging.getLogger(__name__)

T = TypeVar('T')


def with_retry(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
) -> Callable[..., T]:
    """Decorator to add retry with exponential backoff.

    Args:
        func: Function to wrap
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff

    Returns:
        Wrapped function with retry logic
    """
    def wrapper(*args, **kwargs) -> T:
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError) as e:
                last_exception = e
                if attempt < max_retries:
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    logger.warning(
                        f"Redis connection failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Redis connection failed after {max_retries + 1} attempts: {e}"
                    )
        raise last_exception
    return wrapper


class RedisConnection:
    """Manages Redis connections with pooling and retry support."""

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        max_connections: int = 10,
        decode_responses: bool = True,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ):
        """Initialize Redis connection.

        Args:
            url: Redis connection URL
            max_connections: Maximum connections in pool
            decode_responses: Whether to decode responses to strings
            max_retries: Maximum retry attempts for connection errors
            retry_base_delay: Base delay for exponential backoff
        """
        self.url = url
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._max_connections = max_connections
        self._decode_responses = decode_responses
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

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
