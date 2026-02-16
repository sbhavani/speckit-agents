"""Tests for the Mattermost bridge.

Includes both unit tests (mocked SSH) and an integration test that hits
the real OpenClaw + Mattermost stack on mac-mini-i7.local.

Run unit tests:      pytest tests/test_mattermost_bridge.py -m "not integration"
Run integration:     pytest tests/test_mattermost_bridge.py -m integration
Run all:             pytest tests/test_mattermost_bridge.py
"""

import json
import subprocess
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
        bot_token=mm["bot_token"],
        bot_user_id=mm.get("bot_user_id", ""),
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
        bot_token="test_token",
        bot_user_id="bot_user_123",
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
    def test_send_with_sender(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = "{}"
        mock_bridge.send("test message", sender="PM Agent")
        call_args = " ".join(mock_ssh.call_args[0][0])
        assert "PM Agent" in call_args

    @patch("mattermost_bridge.MattermostBridge._ssh")
    def test_send_with_account(self, mock_ssh, mock_bridge):
        mock_ssh.return_value = "{}"
        mock_bridge.send("test")
        call_args = mock_ssh.call_args[0][0]
        assert "--account" in call_args
        assert "testAccount" in call_args


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
        # All messages should be from humans (the bot message should be filtered)
        for msg in human:
            assert msg["user_id"] != bridge.bot_user_id
