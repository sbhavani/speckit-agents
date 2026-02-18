"""Pytest configuration for Redis Streams tests."""

import pytest
import os


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require Redis)"
    )


@pytest.fixture(scope="session")
def redis_url():
    """Get Redis URL from environment or use default."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")
