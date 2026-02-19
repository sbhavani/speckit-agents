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


# ---------------------------------------------------------------------------
# Emoji Test Fixtures
# ---------------------------------------------------------------------------

# Standard emoji samples by category for testing
EMOJI_SMILEYS = ["😀", "😂", "😊", "🙌", "🎉", "😍", "🤔", "😅"]
EMOJI_SYMBOLS = ["✅", "❌", "💯", "🔥", "⭐", "💥", "⚡", "💡"]
EMOJI_FLAGS = ["🇺🇸", "🇬🇧", "🏳️", "🏴‍☠️", "🇨🇦", "🇦🇺", "🇩🇪", "🇫🇷"]
EMOJI_DIVERSE = ["👨‍👩‍👧‍👦", "👩‍❤️‍👩", "🧑‍🦰", "👨🏾", "👩🏻", "🧔‍♂️", "🤵👰", "🧑‍🤝‍🧑"]

# All standard emoji samples combined
STANDARD_EMOJIS = EMOJI_SMILEYS + EMOJI_SYMBOLS + EMOJI_FLAGS + EMOJI_DIVERSE


@pytest.fixture
def emoji_samples():
    """Provide standard emoji samples for testing."""
    return STANDARD_EMOJIS


@pytest.fixture
def emoji_by_category():
    """Provide emoji samples organized by category."""
    return {
        "smiley": EMOJI_SMILEYS,
        "symbol": EMOJI_SYMBOLS,
        "flag": EMOJI_FLAGS,
        "diverse": EMOJI_DIVERSE,
    }


@pytest.fixture
def sample_emoji_message():
    """Provide a sample message with emojis for testing."""
    return "Feature: 🎉 Priority: ✅ Status: 💯"


@pytest.fixture
def complex_emoji_message():
    """Provide a message with complex emoji sequences."""
    return "Team: 👨‍👩‍👧‍👦 Celebration: 🎉"


@pytest.fixture
def mixed_emoji_message():
    """Provide a message with mixed emoji categories."""
    return "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦"
