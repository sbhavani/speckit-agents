"""Redis connection management with connection pooling."""

import logging
import time
from typing import Optional, Callable, TypeVar, Any
import redis
from redis.connection import ConnectionPool

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (redis.ConnectionError, redis.TimeoutError),
):
    """Decorator for retrying operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exceptions to catch and retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * exponential_base, max_delay)
                    else:
                        logger.error(
                            f"Redis operation failed after {max_retries + 1} attempts: {e}"
                        )

            raise last_exception

        return wrapper

    return decorator


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

    @retry_with_backoff(max_retries=3, initial_delay=1.0, max_delay=30.0)
    def connect(self) -> redis.Redis:
        """Create and return a Redis client with retry on connection errors."""
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
