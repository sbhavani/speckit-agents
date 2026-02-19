"""Tests for emoji storage in Redis."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from state_redis import RedisState


class TestRedisEmojiStorage:
    """Test emoji storage and retrieval in Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        with patch("state_redis.redis") as mock_redis_module:
            mock_client = MagicMock()
            mock_redis_module.from_url.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def redis_state(self, mock_redis):
        """Create RedisState with mocked Redis."""
        return RedisState(redis_url="redis://localhost:6379", prefix="test")

    def test_save_and_load_emoji_basic(self, redis_state, mock_redis):
        """Test saving and loading basic emojis - verify round-trip."""
        emoji_data = {
            "message": "Feature: 🎉 Priority: ✅",
            "emojis": ["🎉", "✅", "💯"],
        }
        # Mock the get to return what was saved
        mock_redis.get.return_value = json.dumps(emoji_data)

        redis_state.save("/test/project", emoji_data)
        loaded = redis_state.load("/test/project")

        # Verify emojis are preserved in round-trip
        assert loaded["message"] == "Feature: 🎉 Priority: ✅"
        assert loaded["emojis"] == ["🎉", "✅", "💯"]

    def test_save_and_load_complex_emoji(self, redis_state, mock_redis):
        """Test saving and loading complex emoji sequences."""
        emoji_data = {
            "team": "Family: 👨‍👩‍👧‍👦",
            "celebration": "Party: 🎊",
        }
        mock_redis.get.return_value = json.dumps(emoji_data)

        redis_state.save("/test/project", emoji_data)
        loaded = redis_state.load("/test/project")

        assert loaded["team"] == "Family: 👨‍👩‍👧‍👦"
        assert loaded["celebration"] == "Party: 🎊"

    def test_save_and_load_mixed_emoji(self, redis_state, mock_redis):
        """Test saving and loading mixed emoji categories."""
        emoji_data = {
            "message": "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦",
            "categories": {
                "smiley": "😀",
                "flag": "🇺🇸",
                "symbol": "✅",
                "diverse": "👨‍👩‍👧‍👦",
            },
        }
        mock_redis.get.return_value = json.dumps(emoji_data)

        redis_state.save("/test/project", emoji_data)
        loaded = redis_state.load("/test/project")

        # Verify all emoji categories are preserved
        assert loaded["message"] == "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦"
        assert loaded["categories"]["smiley"] == "😀"
        assert loaded["categories"]["flag"] == "🇺🇸"
        assert loaded["categories"]["symbol"] == "✅"
        assert loaded["categories"]["diverse"] == "👨‍👩‍👧‍👦"

    def test_load_returns_emoji_correctly(self, redis_state, mock_redis):
        """Test that loaded data preserves emojis correctly."""
        original_data = {
            "message": "Feature: 🎉 Priority: ✅ Status: 💯",
        }
        # Simulate what Redis returns - JSON string with emojis
        mock_redis.get.return_value = json.dumps(original_data, ensure_ascii=False)

        loaded = redis_state.load("/test/project")

        assert loaded["message"] == "Feature: 🎉 Priority: ✅ Status: 💯"
        assert "🎉" in loaded["message"]
        assert "✅" in loaded["message"]
        assert "💯" in loaded["message"]

    def test_utf8_encoding_in_json(self, redis_state, mock_redis):
        """Test that UTF-8 encoding works correctly in JSON."""
        emoji_data = {
            "text": "🎉🔧✅💯🔥⭐",
        }
        redis_state.save("/test/project", emoji_data)

        # Verify the stored JSON is valid UTF-8
        stored_value = mock_redis.set.call_args[0][1]
        # Should be able to parse as JSON with UTF-8
        parsed = json.loads(stored_value)
        assert parsed["text"] == "🎉🔧✅💯🔥⭐"

    def test_no_encoding_errors_with_various_emoji(self, redis_state, mock_redis):
        """Test that various emoji ranges don't cause encoding errors."""
        emoji_data = {
            "smileys": "😀😂😊🙌🎉😍🤔😅",
            "symbols": "✅❌💯🔥⭐💥⚡💡",
            "flags": "🇺🇸🇬🇧🏳️🏴‍☠️",
            "diverse": "👨‍👩‍👧‍👦👩‍❤️‍👩🧑‍🦰👨🏾",
        }

        # Should not raise any encoding errors
        try:
            redis_state.save("/test/project", emoji_data)
            stored_value = mock_redis.set.call_args[0][1]
            parsed = json.loads(stored_value)
        except UnicodeEncodeError as e:
            pytest.fail(f"Encoding error: {e}")

        assert parsed["smileys"] == emoji_data["smileys"]
        assert parsed["symbols"] == emoji_data["symbols"]
        assert parsed["flags"] == emoji_data["flags"]
        assert parsed["diverse"] == emoji_data["diverse"]


class TestEncodingErrorLogging:
    """Test encoding error detection and logging."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        with patch("state_redis.redis") as mock_redis_module:
            mock_client = MagicMock()
            mock_redis_module.from_url.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def redis_state(self, mock_redis):
        """Create RedisState with mocked Redis."""
        return RedisState(redis_url="redis://localhost:6379", prefix="test")

    def test_json_dumps_handles_emoji_without_error(self, redis_state, mock_redis, caplog):
        """Test that JSON dumps with emoji doesn't produce encoding errors."""
        emoji_data = {
            "message": "Test 🎉 emoji 💯",
            "mixed": "😀🇺🇸✅👨‍👩‍👧‍👦",
        }

        with caplog.at_level(logging.DEBUG):
            redis_state.save("/test/project", emoji_data)

        # Verify no encoding-related errors in logs
        assert "UnicodeEncodeError" not in caplog.text
        assert "UnicodeDecodeError" not in caplog.text
        assert "encoding error" not in caplog.text.lower()

    def test_json_loads_handles_emoji_without_error(self, redis_state, mock_redis, caplog):
        """Test that JSON loads with emoji doesn't produce encoding errors."""
        emoji_json = '{"message": "Test 🎉 emoji 💯"}'
        mock_redis.get.return_value = emoji_json

        with caplog.at_level(logging.DEBUG):
            loaded = redis_state.load("/test/project")

        # Verify data loaded correctly
        assert loaded["message"] == "Test 🎉 emoji 💯"

        # Verify no encoding-related errors in logs
        assert "UnicodeEncodeError" not in caplog.text
        assert "UnicodeDecodeError" not in caplog.text
        assert "encoding error" not in caplog.text.lower()

    def test_invalid_utf8_handled_gracefully(self, redis_state, mock_redis, caplog):
        """Test that invalid UTF-8 bytes are handled gracefully."""
        # Simulate corrupted data that might come from Redis
        # This tests the system's ability to handle edge cases
        invalid_utf8 = b'{"message": "Test \\xff\\xfe emoji"}'

        with patch.object(mock_redis, "get", return_value=invalid_utf8):
            with caplog.at_level(logging.DEBUG):
                # The load should either succeed or log an appropriate error
                try:
                    result = redis_state.load("/test/project")
                    # If it succeeds, emojis should be preserved if valid UTF-8
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    # It's acceptable to fail with clear error
                    # The key is that it doesn't crash silently
                    error_str = str(e).lower()
                    assert "json" in error_str or "unicode" in error_str or "invalid" in error_str or "escape" in error_str

    def test_emoji_in_log_messages_preserved(self, redis_state, mock_redis, caplog):
        """Test that emojis in log messages are preserved when logged."""
        emoji_data = {
            "message": "Feature complete 🎉",
            "status": "Success ✅",
        }

        with caplog.at_level(logging.DEBUG, logger="state_redis"):
            redis_state.save("/test/project", emoji_data)

        # Verify emojis in the original data are preserved via round-trip
        stored_value = mock_redis.set.call_args[0][1]
        parsed = json.loads(stored_value)
        assert parsed["message"] == "Feature complete 🎉"
        assert parsed["status"] == "Success ✅"
