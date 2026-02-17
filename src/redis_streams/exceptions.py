"""Redis Streams exception classes."""


class RedisStreamsError(Exception):
    """Base exception for Redis Streams errors."""
    pass


class StreamNotFoundError(RedisStreamsError):
    """Raised when a stream does not exist."""
    def __init__(self, stream: str):
        self.stream = stream
        super().__init__(f"Stream not found: {stream}")


class GroupNotFoundError(RedisStreamsError):
    """Raised when a consumer group does not exist."""
    def __init__(self, group: str, stream: str = None):
        self.group = group
        self.stream = stream
        msg = f"Consumer group not found: {group}"
        if stream:
            msg += f" (stream: {stream})"
        super().__init__(msg)


class ConsumerNotFoundError(RedisStreamsError):
    """Raised when a consumer does not exist."""
    def __init__(self, consumer: str, group: str):
        self.consumer = consumer
        self.group = group
        super().__init__(f"Consumer not found: {consumer} in group {group}")


class PayloadTooLargeError(RedisStreamsError):
    """Raised when event payload exceeds size limit."""
    def __init__(self, size: int, max_size: int = 1024 * 1024):
        self.size = size
        self.max_size = max_size
        super().__init__(f"Payload size {size} exceeds maximum {max_size} bytes")


class ConsumerCrashedError(RedisStreamsError):
    """Raised when a consumer has been inactive too long."""
    def __init__(self, consumer: str, idle_ms: int):
        self.consumer = consumer
        self.idle_ms = idle_ms
        super().__init__(f"Consumer {consumer} crashed (idle {idle_ms}ms)")


class RedisConnectionError(RedisStreamsError):
    """Raised when connection to Redis fails."""
    def __init__(self, message: str = "Failed to connect to Redis"):
        super().__init__(message)


class ValidationError(RedisStreamsError):
    """Raised when validation fails."""
    pass


class StreamExistsError(RedisStreamsError):
    """Raised when attempting to create an existing stream."""
    def __init__(self, stream: str):
        self.stream = stream
        super().__init__(f"Stream already exists: {stream}")


class GroupExistsError(RedisStreamsError):
    """Raised when attempting to create an existing group."""
    def __init__(self, group: str, stream: str = None):
        self.group = group
        self.stream = stream
        msg = f"Consumer group already exists: {group}"
        if stream:
            msg += f" (stream: {stream})"
        super().__init__(msg)
