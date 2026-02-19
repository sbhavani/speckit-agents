"""Tests for the Mattermost bridge.

Includes both unit tests (mocked SSH) and an integration test that hits
the real OpenClaw + Mattermost stack on mac-mini-i7.local.

Run unit tests:      pytest tests/test_mattermost_bridge.py -m "not integration"
Run integration:     pytest tests/test_mattermost_bridge.py -m integration
Run all:             pytest tests/test_mattermost_bridge.py
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mattermost_bridge import MattermostBridge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIG_PATH = "config.yaml"


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _make_bridge_from_config():
    cfg = _load_config()
    mm = cfg["mattermost"]
    return MattermostBridge(
        ssh_host=cfg["openclaw"]["ssh_host"],
        channel_id=mm["channel_id"],
        mattermost_url=mm.get("url", "http://localhost:8065"),
        dev_bot_token=mm["dev_bot_token"],
        dev_bot_user_id=mm.get("dev_bot_user_id", ""),
        pm_bot_token=mm.get("pm_bot_token", ""),
        pm_bot_user_id=mm.get("pm_bot_user_id", ""),
        openclaw_account=cfg["openclaw"].get("openclaw_account"),
    )


@pytest.fixture
def bridge():
    """A bridge wired to the real config (for integration tests)."""
    return _make_bridge_from_config()


@pytest.fixture
def mock_bridge():
    """A bridge with a mocked SSH layer (for unit tests)."""
    return MattermostBridge(
        ssh_host="test@host",
        channel_id="test_channel_id",
        mattermost_url="http://localhost:8065",
        dev_bot_token="test_token",
        dev_bot_user_id="bot_user_123",
        pm_bot_token="pm_token_456",
        pm_bot_user_id="pm_user_456",
        openclaw_account="testAccount",
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestShellQuote:
    def test_simple_string(self):
        assert MattermostBridge._shell_quote("hello") == "$'hello'"

    def test_single_quotes(self):
        result = MattermostBridge._shell_quote("it's a test")
        assert "\\'" in result

    def test_newlines(self):
        result = MattermostBridge._shell_quote("line1\nline2")
        assert "\\n" in result

    def test_backslashes(self):
        result = MattermostBridge._shell_quote("path\\to\\file")
        assert "\\\\" in result


class TestSend:
    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_basic(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = '{"result": {"messageId": "abc123"}}'
        result = mock_bridge.send("hello world")
        mock_ssh.assert_called_once()
        call_args = mock_ssh.call_args[0][0]
        assert "openclaw" in call_args
        assert "message" in call_args
        assert "send" in call_args
        assert "channel:test_channel_id" in " ".join(call_args)
        assert result["result"]["messageId"] == "abc123"

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_pm_uses_api(self, mock_ssh, mock_bridge):
        """PM Agent messages should go via Mattermost API (product-manager bot)."""
        mock_ssh.return_value = '{"id": "post123"}'
        mock_bridge.send("test message", sender="PM Agent")
        call_args = " ".join(mock_ssh.call_args[0][0])
        # Should use curl POST to /api/v4/posts, not openclaw CLI
        assert "curl" in call_args
        assert "/api/v4/posts" in call_args
        assert "pm_token_456" in call_args

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_dev_uses_openclaw(self, mock_ssh, mock_bridge):
        """Dev Agent messages should go via OpenClaw CLI."""
        mock_ssh.return_value = "{}"
        mock_bridge.send("test message", sender="Dev Agent")
        call_args = " ".join(mock_ssh.call_args[0][0])
        assert "openclaw" in call_args
        assert "--account" in call_args
        assert "testAccount" in call_args

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_orchestrator_uses_openclaw(self, mock_ssh, mock_bridge):
        """Orchestrator messages should go via OpenClaw CLI."""
        mock_ssh.return_value = "{}"
        mock_bridge.send("test", sender="Orchestrator")
        call_args = " ".join(mock_ssh.call_args[0][0])
        assert "openclaw" in call_args

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_with_emoji_basic(self, mock_ssh, mock_bridge):
        """Messages with basic emojis should be preserved via Unicode escapes."""
        mock_ssh.return_value = "{}"
        emoji_message = "Feature: 🎉 Priority: ✅ Status: 💯"
        mock_bridge.send(emoji_message, sender="PM Agent")
        # Verify the emoji message is encoded as Unicode escapes in the JSON payload
        call_args = " ".join(mock_ssh.call_args[0][0])
        # Emojis are converted to \\\\uXXXX format by json.dumps + shell quoting
        assert "\\\\ud83c\\\\udf89" in call_args  # 🎉
        assert "\\\\u2705" in call_args            # ✅
        assert "\\\\ud83d\\\\udcaf" in call_args   # 💯

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_with_emoji_complex_sequence(self, mock_ssh, mock_bridge):
        """Messages with complex emoji sequences should be preserved."""
        mock_ssh.return_value = "{}"
        complex_message = "Team: 👨‍👩‍👧‍👦 Celebration: 🎉"
        mock_bridge.send(complex_message, sender="Dev Agent")
        call_args = " ".join(mock_ssh.call_args[0][0])
        # Complex emoji sequences use zero-width joiners encoded as \\u200d
        assert "\\\\ud83d\\\\udc68\\\\u200d\\\\ud83d\\\\udc69\\\\u200d\\\\ud83d\\\\udc67\\\\u200d\\\\ud83d\\\\udc66" in call_args
        assert "\\\\ud83c\\\\udf89" in call_args

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_with_emoji_mixed_categories(self, mock_ssh, mock_bridge):
        """Messages with mixed emoji categories should be preserved."""
        mock_ssh.return_value = "{}"
        mixed_message = "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦"
        mock_bridge.send(mixed_message, sender="PM Agent")
        call_args = " ".join(mock_ssh.call_args[0][0])
        # Verify various emoji categories are encoded
        assert "\\\\ud83d\\\\ude00" in call_args    # 😀
        assert "\\\\ud83c\\\\uddfa\\\\ud83c\\\\uddf8" in call_args  # 🇺🇸
        assert "\\\\u2705" in call_args            # ✅
        assert "\\\\ud83d\\\\udc68\\\\u200d\\\\ud83d\\\\udc69\\\\u200d\\\\ud83d\\\\udc67\\\\u200d\\\\ud83d\\\\udc66" in call_args  # 👨‍👩‍👧‍👦


class TestReadPosts:
    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_read_posts_parses_response(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["post1", "post2"],
            "posts": {
                "post1": {
                    "id": "post1", "message": "first", "user_id": "u1",
                    "create_at": 1000, "type": "",
                },
                "post2": {
                    "id": "post2", "message": "second", "user_id": "u2",
                    "create_at": 2000, "type": "",
                },
            },
        })
        posts = mock_bridge.read_posts(limit=5)
        assert len(posts) == 2
        # Should be sorted oldest first
        assert posts[0]["id"] == "post1"
        assert posts[1]["id"] == "post2"

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_read_posts_empty(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({"order": [], "posts": {}})
        posts = mock_bridge.read_posts()
        assert posts == []

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_read_posts_bad_json(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = "not json"
        posts = mock_bridge.read_posts()
        assert posts == []


class TestReadNewHumanMessages:
    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_filters_bot_messages(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["p1", "p2"],
            "posts": {
                "p1": {
                    "id": "p1", "message": "bot msg", "user_id": "bot_user_123",
                    "create_at": 2000, "type": "",
                },
                "p2": {
                    "id": "p2", "message": "human msg", "user_id": "human_456",
                    "create_at": 3000, "type": "",
                },
            },
        })
        mock_bridge._last_seen_ts = 1000
        human = mock_bridge.read_new_human_messages()
        assert len(human) == 1
        assert human[0]["message"] == "human msg"

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_filters_pm_bot_messages(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["p1", "p2"],
            "posts": {
                "p1": {
                    "id": "p1", "message": "pm bot msg", "user_id": "pm_user_456",
                    "create_at": 2000, "type": "",
                },
                "p2": {
                    "id": "p2", "message": "human msg", "user_id": "human_789",
                    "create_at": 3000, "type": "",
                },
            },
        })
        mock_bridge._last_seen_ts = 1000
        human = mock_bridge.read_new_human_messages()
        assert len(human) == 1
        assert human[0]["message"] == "human msg"

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_filters_system_messages(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["p1"],
            "posts": {
                "p1": {
                    "id": "p1", "message": "joined", "user_id": "u1",
                    "create_at": 2000, "type": "system_join_channel",
                },
            },
        })
        mock_bridge._last_seen_ts = 1000
        human = mock_bridge.read_new_human_messages()
        assert human == []

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_updates_last_seen_ts(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["p1"],
            "posts": {
                "p1": {
                    "id": "p1", "message": "hi", "user_id": "human_456",
                    "create_at": 5000, "type": "",
                },
            },
        })
        mock_bridge._last_seen_ts = 1000
        mock_bridge.read_new_human_messages()
        assert mock_bridge._last_seen_ts == 5000

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_skips_already_seen(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = json.dumps({
            "order": ["p1"],
            "posts": {
                "p1": {
                    "id": "p1", "message": "old", "user_id": "human_456",
                    "create_at": 1000, "type": "",
                },
            },
        })
        mock_bridge._last_seen_ts = 1000
        human = mock_bridge.read_new_human_messages()
        assert human == []


class TestSSHBannerFiltering:
    @patch("subprocess.run")
    def test_filters_banner_from_stdout(self, mock_run, mock_bridge):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "*******************************************\n"
                "       UNAUTHORIZED ACCESS PROHIBITED\n"
                "*******************************************\n"
                "All connections are monitored and logged.\n"
                "Disconnect immediately if you are not authorized.\n"
                '{"result": "clean"}\n'
            ),
            stderr="",
        )
        output = mock_bridge._ssh(["echo", "test"])
        assert output == '{"result": "clean"}'


# ---------------------------------------------------------------------------
# Integration tests (require SSH access to mac-mini-i7.local + OpenClaw)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegrationSendRead:
    """Live tests against the real Mattermost instance.

    Run with: pytest tests/test_mattermost_bridge.py -m integration -v
    """

    def test_send_and_read_roundtrip(self, bridge):
        """Send a message and verify it appears in the channel posts."""
        tag = f"integration-test-{int(time.time())}"
        bridge.send(f"Roundtrip test: {tag}", sender="Test")

        # Give Mattermost a moment to index the post
        time.sleep(2)

        posts = bridge.read_posts(limit=5)
        messages = [p["message"] for p in posts]
        assert any(tag in m for m in messages), (
            f"Expected to find '{tag}' in recent posts, got: {messages}"
        )

    def test_read_posts_returns_valid_structure(self, bridge):
        """Verify read_posts returns well-structured data."""
        posts = bridge.read_posts(limit=3)
        assert isinstance(posts, list)
        for p in posts:
            assert "id" in p
            assert "message" in p
            assert "user_id" in p
            assert "create_at" in p
            assert isinstance(p["create_at"], int)

    def test_human_filter_excludes_bot(self, bridge):
        """Verify that read_new_human_messages filters out bot posts."""
        # Send a bot message
        bridge.send("Bot message for filter test")
        time.sleep(2)

        # Mark position after the bot message
        bridge.mark_current_position()

        # Read new human messages — should be empty since only the bot posted
        human = bridge.read_new_human_messages()
        # All messages should be from humans (bot messages should be filtered)
        for msg in human:
            assert msg["user_id"] not in bridge.bot_user_ids
