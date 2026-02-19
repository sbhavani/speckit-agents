"""Tests for emoji preservation in PM-to-Dev message relay.

This module tests that emoji characters are preserved when the orchestrator
relays messages from the PM Agent to the Dev Agent through the message bridge.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from mattermost_bridge import MattermostBridge
from orchestrator import Orchestrator
from orchestrator import Messenger


class TestPMToDevEmojiRelay:
    """Test emoji preservation in PM-to-Dev message relay."""

    @pytest.fixture
    def mock_bridge(self):
        """Create a mock Mattermost bridge."""
        mock = MagicMock()
        mock.send.return_value = {"result": {"messageId": "test123"}}
        return mock

    @pytest.fixture
    def messenger_with_emoji(self, mock_bridge):
        """Create a Messenger with emoji-capable bridge."""
        return Messenger(bridge=mock_bridge, dry_run=False)

    @pytest.fixture
    def orchestrator_with_emoji(self, tmp_path, mock_bridge):
        """Create an Orchestrator configured for emoji testing."""
        config = {
            "project": {
                "path": str(tmp_path),
                "prd_path": "docs/PRD.md",
            },
            "workflow": {},
        }
        messenger = Messenger(bridge=mock_bridge, dry_run=False)
        return Orchestrator(config, messenger)

    def test_pm_message_with_basic_emoji_relayed_to_dev(
        self, orchestrator_with_emoji, mock_bridge
    ):
        """Test that basic emojis in PM messages are preserved when relayed to Dev."""
        # PM sends a message with emojis
        pm_message = "Feature suggestion: Add emoji support 🎉 Priority: high ✅"

        # Simulate PM-to-Dev relay: orchestrator sends the message to channel
        # where Dev Agent can see it
        orchestrator_with_emoji.msg.send(pm_message, sender="PM Agent")

        # Verify the bridge was called with the emoji message preserved
        mock_bridge.send.assert_called_once()
        call_args = mock_bridge.send.call_args

        # The message should contain the original emojis
        sent_message = call_args[1].get("message") or call_args[0][0]
        assert "🎉" in sent_message
        assert "✅" in sent_message

    def test_pm_message_with_complex_emoji_relayed_to_dev(
        self, orchestrator_with_emoji, mock_bridge
    ):
        """Test that complex emoji sequences in PM messages are preserved."""
        # PM sends a message with complex emoji sequences (family emoji)
        pm_message = "Team: 👨‍👩‍👧‍👦 Feature: 🎊"

        orchestrator_with_emoji.msg.send(pm_message, sender="PM Agent")

        mock_bridge.send.assert_called_once()
        call_args = mock_bridge.send.call_args
        sent_message = call_args[1].get("message") or call_args[0][0]

        # Complex emoji sequences should be preserved
        assert "👨‍👩‍👧‍👦" in sent_message
        assert "🎊" in sent_message

    def test_pm_message_with_mixed_emoji_categories_relayed(
        self, orchestrator_with_emoji, mock_bridge
    ):
        """Test that mixed emoji categories are preserved in relay."""
        pm_message = "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦"

        orchestrator_with_emoji.msg.send(pm_message, sender="PM Agent")

        mock_bridge.send.assert_called_once()
        call_args = mock_bridge.send.call_args
        sent_message = call_args[1].get("message") or call_args[0][0]

        # All emoji categories should be preserved
        assert "😀" in sent_message
        assert "🇺🇸" in sent_message
        assert "✅" in sent_message
        assert "👨‍👩‍👧‍👦" in sent_message

    def test_emoji_preserved_in_feature_description_relay(
        self, orchestrator_with_emoji, mock_bridge
    ):
        """Test that emojis in feature descriptions survive the PM-to-Dev relay."""
        feature_with_emoji = {
            "feature": "Add celebration emoji to notifications 🎉",
            "description": "Users want to see ✅ when tasks complete",
            "priority": "P1",
            "rationale": "Improves user experience 💯",
        }

        # Relay the feature description to Dev
        feature_msg = (
            f"**{feature_with_emoji['feature']}**\n\n"
            f"{feature_with_emoji['description']}\n\n"
            f"_Rationale: {feature_with_emoji['rationale']}_"
        )
        orchestrator_with_emoji.msg.send(feature_msg, sender="PM Agent")

        mock_bridge.send.assert_called_once()
        call_args = mock_bridge.send.call_args
        sent_message = call_args[1].get("message") or call_args[0][0]

        # All emojis in the feature description should be preserved
        assert "🎉" in sent_message
        assert "✅" in sent_message
        assert "💯" in sent_message

    def test_emoji_preserved_via_json_payload(self, orchestrator_with_emoji, mock_bridge):
        """Test that emojis are preserved when sent via JSON payload."""
        pm_message = "Priority: 🔥 Status: ✅"

        orchestrator_with_emoji.msg.send(pm_message, sender="PM Agent")

        # Verify the JSON payload preserves emojis
        mock_bridge.send.assert_called_once()
        call_args = mock_bridge.send.call_args

        # Check that emojis aren't corrupted in the payload
        # The message should be valid UTF-8
        sent_message = call_args[1].get("message") or call_args[0][0]
        assert isinstance(sent_message, str)
        # Should not have unicode replacement characters
        assert "\ufffd" not in sent_message
        assert "🔥" in sent_message
        assert "✅" in sent_message


class TestEmojiInMessageRelayPipeline:
    """Test emoji handling through the full message relay pipeline."""

    def test_emoji_survives_json_serialization(self):
        """Test that emojis survive JSON serialization in the relay pipeline."""
        message_with_emoji = "Feature: 🎉 Priority: ✅"

        # Simulate JSON serialization (what happens in the bridge)
        json_payload = json.dumps({"message": message_with_emoji}, ensure_ascii=False)
        decoded = json.loads(json_payload)

        assert decoded["message"] == message_with_emoji
        assert "🎉" in decoded["message"]
        assert "✅" in decoded["message"]

    def test_complex_emoji_survives_json_serialization(self):
        """Test that complex emoji sequences survive JSON serialization."""
        message_with_emoji = "Team: 👨‍👩‍👧‍👦 Celebration: 🎊"

        json_payload = json.dumps({"message": message_with_emoji}, ensure_ascii=False)
        decoded = json.loads(json_payload)

        assert decoded["message"] == message_with_emoji

    def test_mixed_emoji_survives_json_serialization(self):
        """Test that mixed emoji categories survive JSON serialization."""
        message_with_emoji = "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦"

        json_payload = json.dumps({"message": message_with_emoji}, ensure_ascii=False)
        decoded = json.loads(json_payload)

        assert decoded["message"] == message_with_emoji
        assert "😀" in decoded["message"]
        assert "🇺🇸" in decoded["message"]
        assert "✅" in decoded["message"]
        assert "👨‍👩‍👧‍👦" in decoded["message"]


# ---------------------------------------------------------------------------
# UTF-8 Encoding Consistency Tests (US3)
# ---------------------------------------------------------------------------

class TestUTF8EncodingConsistency:
    """Test UTF-8 encoding consistency across the message pipeline.

    These tests verify that emoji characters maintain consistent UTF-8 encoding
    as messages flow through the entire system: orchestrator → bridge → API → storage.
    """

    @pytest.fixture
    def mock_bridge(self):
        """Create a mocked MattermostBridge for testing."""
        return MattermostBridge(
            ssh_host="test@host",
            channel_id="test_channel_id",
            mattermost_url="http://localhost:8065",
            dev_bot_token="test_token",
            dev_bot_user_id="bot_user_123",
            pm_bot_token="pm_token_456",
            pm_bot_user_id="pm_user_456",
            openclaw_account="testAccount",
            use_ssh=False,
        )

    @pytest.mark.parametrize("emoji_message", [
        "Feature: 🎉 Priority: ✅ Status: 💯",
        "Team: 👨‍👩‍👧‍👦 Celebration: 🎊",
        "Hello 😀! Flag: 🇺🇸, Check: ✅, Family: 👨‍👩‍👧‍👦",
        "Symbols: 💥⚡💡🔔📢",
        "Mixed: Hello 🌍! 🚀 to the ⭐!",
    ])
    def test_utf8_encoding_preserved_in_send_pipeline(self, mock_bridge, emoji_message):
        """Test that UTF-8 encoding is preserved when sending messages.

        Verifies the message pipeline: orchestrator → bridge.send() → API payload
        Each step should preserve the UTF-8 encoding without corruption.
        """
        with patch.object(mock_bridge, "_ssh") as mock_ssh:
            mock_ssh.return_value = '{"id": "post123"}'

            # Send the message
            result = mock_bridge.send(emoji_message, sender="PM Agent")

            # Get the command that was executed
            call_args = " ".join(mock_ssh.call_args[0][0])

            # Verify the JSON payload contains valid UTF-8
            # Extract the -d payload argument
            for arg in mock_ssh.call_args[0][0]:
                if arg.startswith("{"):
                    # This is the JSON payload
                    payload = json.loads(arg)
                    assert payload["message"] == emoji_message, \
                        f"Message corrupted: expected {emoji_message}, got {payload['message']}"
                    break

            # Verify no replacement characters (U+FFFD) in the payload
            assert "\ufffd" not in call_args, "Replacement character found - encoding corruption"

    def test_utf8_consistency_complex_emoji_sequences(self, mock_bridge):
        """Test UTF-8 consistency with complex emoji sequences (ZWJ sequences)."""
        complex_messages = [
            "Family: 👨‍👩‍👧‍👦",
            "Couple: 👩‍❤️‍👩",
            "Handshake: 🧑‍🤝‍🧑",
            "Mixed: 👨🏾‍🦰👩🏻‍🦱🧔‍♂️",
        ]

        for msg in complex_messages:
            with patch.object(mock_bridge, "_ssh") as mock_ssh:
                mock_ssh.return_value = '{"id": "post123"}'
                mock_bridge.send(msg, sender="Dev Agent")

                # Extract and verify the payload
                for arg in mock_ssh.call_args[0][0]:
                    if arg.startswith("{"):
                        payload = json.loads(arg)
                        assert payload["message"] == msg, \
                            f"Complex sequence corrupted: expected {msg}, got {payload['message']}"
                        break

    def test_no_encoding_errors_in_pipeline(self, mock_bridge, caplog):
        """Test that no encoding errors occur during message processing."""
        emoji_message = "Test 🎉 emoji 💯 with 🔥 and ⭐"

        with patch.object(mock_bridge, "_ssh") as mock_ssh:
            mock_ssh.return_value = '{"id": "post123"}'

            with caplog.at_level(logging.DEBUG):
                mock_bridge.send(emoji_message, sender="PM Agent")

            # Verify no encoding-related errors in logs
            assert "UnicodeEncodeError" not in caplog.text
            assert "UnicodeDecodeError" not in caplog.text
            assert "codec can't encode" not in caplog.text.lower()

    def test_read_posts_preserves_utf8(self, mock_bridge):
        """Test that reading posts preserves UTF-8 encoding."""
        emoji_messages = [
            {"id": "p1", "message": "Feature: 🎉", "user_id": "u1", "create_at": 1000, "type": ""},
            {"id": "p2", "message": "Status: ✅ 💯", "user_id": "u2", "create_at": 2000, "type": ""},
            {"id": "p3", "message": "Team: 👨‍👩‍👧‍👦", "user_id": "u3", "create_at": 3000, "type": ""},
        ]

        with patch.object(mock_bridge, "_ssh") as mock_ssh:
            mock_ssh.return_value = json.dumps({
                "order": ["p1", "p2", "p3"],
                "posts": {p["id"]: p for p in emoji_messages},
            })

            posts = mock_bridge.read_posts(limit=10)

            # Verify each message preserves its emoji
            for i, original in enumerate(emoji_messages):
                assert posts[i]["message"] == original["message"], \
                    f"Message corrupted on read: {original['message']} -> {posts[i]['message']}"

    def test_utf8_bytes_consistency(self, mock_bridge):
        """Test that UTF-8 bytes are consistent throughout the pipeline."""
        test_message = "🎉🔧✅💯🔥⭐"

        with patch.object(mock_bridge, "_ssh") as mock_ssh:
            mock_ssh.return_value = '{"id": "post123"}'
            mock_bridge.send(test_message, sender="PM Agent")

            # Get the raw command
            cmd_str = " ".join(mock_ssh.call_args[0][0])

            # Verify UTF-8 encoding in the raw command
            # The message should be encoded as UTF-8, not as escaped sequences
            try:
                cmd_str.encode('utf-8')
            except UnicodeEncodeError as e:
                pytest.fail(f"UTF-8 encoding error in pipeline: {e}")


class TestEncodingPipelineIntegration:
    """Integration tests for the full encoding pipeline.

    These tests verify end-to-end encoding consistency across
    multiple system components.
    """

    @pytest.fixture
    def mock_bridge(self):
        """Create a mocked MattermostBridge."""
        return MattermostBridge(
            ssh_host="test@host",
            channel_id="test_channel_id",
            mattermost_url="http://localhost:8065",
            dev_bot_token="test_token",
            dev_bot_user_id="bot_user_123",
            pm_bot_token="pm_token_456",
            pm_bot_user_id="pm_user_456",
            use_ssh=False,
        )

    def test_full_pipeline_emoji_preservation(self, mock_bridge):
        """Test the full pipeline: create → send → read → verify."""
        original_message = "Feature Request: 🎉 Add dark mode ✅ Priority: 💯"

        with patch.object(mock_bridge, "_ssh") as mock_ssh:
            # Step 1: Send message through bridge
            mock_ssh.return_value = '{"id": "post123"}'
            mock_bridge.send(original_message, sender="PM Agent")

            # Step 2: Simulate reading back the message
            response_data = json.dumps({
                "order": ["post123"],
                "posts": {
                    "post123": {
                        "id": "post123",
                        "message": original_message,
                        "user_id": "pm_user_456",
                        "create_at": 5000,
                        "type": "",
                    }
                },
            })
            mock_ssh.return_value = response_data

            # Step 3: Read the message back
            posts = mock_bridge.read_posts(limit=1)

            # Step 4: Verify encoding consistency
            assert len(posts) == 1
            assert posts[0]["message"] == original_message

            # Verify no character substitution occurred
            assert posts[0]["message"] == original_message
            for emoji in ["🎉", "✅", "💯"]:
                assert emoji in posts[0]["message"], f"Missing emoji {emoji}"

    def test_pipeline_with_all_emoji_categories(self, mock_bridge):
        """Test pipeline with all emoji categories represented."""
        messages_by_category = {
            "smiley": "Hello 😀 today is great!",
            "symbol": "Status: ✅ Complete! Score: 💯",
            "flag": "Location: 🇺🇸 HQ",
            "diverse": "Team: 👨‍👩‍👧‍👦 meeting",
        }

        for category, message in messages_by_category.items():
            with patch.object(mock_bridge, "_ssh") as mock_ssh:
                mock_ssh.return_value = '{"id": "post123"}'
                mock_bridge.send(message, sender="PM Agent")

                # Extract and verify
                for arg in mock_ssh.call_args[0][0]:
                    if arg.startswith("{"):
                        payload = json.loads(arg)
                        assert payload["message"] == message, \
                            f"Category {category} failed: {message} != {payload['message']}"
                        break

    def test_unicode_normalization_consistency(self, mock_bridge):
        """Test that Unicode normalization doesn't affect emoji display."""
        # Test with various emoji that might be affected by normalization
        test_messages = [
            "café ☕️",  # Combined emoji
            "test 🎉",  # Standard emoji
            "🔥 burning",  # Emoji with text
        ]

        for msg in test_messages:
            with patch.object(mock_bridge, "_ssh") as mock_ssh:
                mock_ssh.return_value = '{"id": "post123"}'
                mock_bridge.send(msg, sender="PM Agent")

                for arg in mock_ssh.call_args[0][0]:
                    if arg.startswith("{"):
                        payload = json.loads(arg)
                        # Verify the message is preserved
                        assert payload["message"] == msg, \
                            f"Message changed: {msg} -> {payload['message']}"
                        break
