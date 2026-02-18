"""Redis connection management with connection pooling."""

import time
import logging
from typing import Optional, Callable, Any
import redis
from redis.connection import ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)


def retry_with_exponential_backoff(
    max_retries: int = 5,
    base_delay: float = 0.1,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (ConnectionError, RedisTimeoutError),
) -> Callable:
    """Decorator for retrying functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential calculation
        retryable_exceptions: Tuple of exceptions that trigger retry

    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) reached for {func.__name__}"
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.2f}s delay. Error: {e}"
                    )
                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
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
        max_retries: int = 5,
        retry_base_delay: float = 0.1,
        retry_max_delay: float = 30.0,
    ):
        """Initialize Redis connection.

        Args:
            url: Redis connection URL
            max_connections: Maximum connections in pool
            decode_responses: Whether to decode responses to strings
            max_retries: Maximum retry attempts for connection errors
            retry_base_delay: Initial delay for exponential backoff
            retry_max_delay: Maximum delay between retries
        """
        self.url = url
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._max_connections = max_connections
        self._decode_responses = decode_responses
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay

    @retry_with_exponential_backoff(
        max_retries=5,
        base_delay=0.1,
        max_delay=30.0,
    )
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

    @retry_with_exponential_backoff(
        max_retries=3,
        base_delay=0.1,
        max_delay=5.0,
    )
    def ping(self) -> bool:
        """Check if Redis is available."""
        return self.client.ping()

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
