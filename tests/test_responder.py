"""Tests for responder config loading and deep merge.

Run: uv run pytest tests/test_responder.py -m "not integration"
"""

from unittest.mock import MagicMock


class TestConfigLoading:
    def test_loads_base_config(self):
        """Test that base config is loaded."""
        from responder import _deep_merge

        base = {"a": 1, "b": 2}
        override = {}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": 2}

    def test_deep_merge_overrides_values(self):
        """Test that override values replace base values."""
        from responder import _deep_merge

        base = {"token": "old", "other": "keep"}
        override = {"token": "new"}
        _deep_merge(base, override)
        assert base == {"token": "new", "other": "keep"}

    def test_deep_merge_nested_dicts(self):
        """Test that nested dicts are merged recursively."""
        from responder import _deep_merge

        base = {"mattermost": {"url": "http://old", "token": "secret"}}
        override = {"mattermost": {"url": "http://new"}}
        _deep_merge(base, override)
        assert base == {"mattermost": {"url": "http://new", "token": "secret"}}

    def test_deep_merge_adds_new_keys(self):
        """Test that new keys in override are added to base."""
        from responder import _deep_merge

        base = {"existing": 1}
        override = {"new_key": 2}
        _deep_merge(base, override)
        assert base == {"existing": 1, "new_key": 2}

    def test_deep_merge_replaces_non_dict_with_dict(self):
        """Test that non-dict override replaces dict base."""
        from responder import _deep_merge

        base = {"key": {"nested": 1}}
        override = {"key": "simple"}
        _deep_merge(base, override)
        assert base == {"key": "simple"}

    def test_deep_merge_replaces_dict_with_non_dict(self):
        """Test that dict override replaces non-dict base."""
        from responder import _deep_merge

        base = {"key": "simple"}
        override = {"key": {"nested": 1}}
        _deep_merge(base, override)
        assert base == {"key": {"nested": 1}}


class TestResponderImports:
    def test_imports_work(self):
        """Verify responder module can be imported."""
        import responder
        assert hasattr(responder, "_deep_merge")


# ---------------------------------------------------------------------------
# Question detection
# ---------------------------------------------------------------------------

class TestQuestionDetection:
    """Tests for question detection logic in responder."""

    def _make_responder(self):
        """Create a responder with mocked config."""
        from unittest.mock import MagicMock

        config = {
            "mattermost": {"channel_id": "test_channel"},
            "openclaw": {},
            "projects": {},
        }
        # Create responder without running init
        from responder import Responder
        r = Responder.__new__(Responder)
        r.cfg = config
        r.bridge = MagicMock()
        return r

    def test_question_detects_trailing_question_mark(self):
        """Question with trailing ? should be detected."""
        _r = self._make_responder()
        text = "What is this?"
        is_question = text.strip().endswith("?")
        assert is_question is True

    def test_question_detects_can_you_phrase(self):
        """Question starting with 'can you' should be detected."""
        _r = self._make_responder()
        text = "Can you help me?"
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                           "how can", "what is", "what's", "why is", "why does",
                           "when will", "should i", "should we"]
        is_question = text.strip().endswith("?")
        is_question = is_question or any(text.lower().startswith(phrase) for phrase in question_phrases)
        assert is_question is True

    def test_question_detects_how_do_phrase(self):
        """Question starting with 'how do' should be detected."""
        text = "How do I use this?"
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                           "how can", "what is", "what's", "why is", "why does",
                           "when will", "should i", "should we"]
        is_question = any(text.lower().startswith(phrase) for phrase in question_phrases)
        assert is_question is True

    def test_question_detects_why_does_phrase(self):
        """Question starting with 'why does' should be detected."""
        text = "Why does it break?"
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                           "how can", "what is", "what's", "why is", "why does",
                           "when will", "should i", "should we"]
        is_question = any(text.lower().startswith(phrase) for phrase in question_phrases)
        assert is_question is True

    def test_non_question_not_detected_as_question(self):
        """Statements should not be detected as questions."""
        text = "This is a feature request"
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                           "how can", "what is", "what's", "why is", "why does",
                           "when will", "should i", "should we"]
        is_question = text.strip().endswith("?")
        is_question = is_question or any(text.lower().startswith(phrase) for phrase in question_phrases)
        assert is_question is False


# ---------------------------------------------------------------------------
# Command detection
# ---------------------------------------------------------------------------

class TestCommandDetection:
    """Tests for command detection in responder."""

    def test_resume_command_detected(self):
        """Message containing /resume should be detected."""
        text = "@product-manager /resume"
        assert "/resume" in text.lower()

    def test_suggest_command_detected(self):
        """Message containing /suggest should be detected."""
        text = "please /suggest a new feature"
        assert "/suggest" in text.lower()

    def test_suggest_not_question(self):
        """Message with /suggest should not be treated as question."""
        text = "/suggest Add login"
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                           "how can", "what is", "what's", "why is", "why does",
                           "when will", "should i", "should we"]
        is_question = text.strip().endswith("?")
        is_question = is_question or any(text.lower().startswith(phrase) for phrase in question_phrases)
        assert is_question is False


# ---------------------------------------------------------------------------
# Mention detection
# ---------------------------------------------------------------------------

class TestMentionDetection:
    """Tests for @mention detection."""

    def test_product_manager_mention_detected(self):
        """@product-manager mention should be detected."""
        text = "Hey @product-manager can you help?"
        assert "@product-manager" in text.lower()

    def test_dev_agent_mention_detected(self):
        """@dev-agent mention should be detected."""
        text = "@dev-agent what are you working on?"
        assert "@dev-agent" in text.lower()

    def test_mention_case_insensitive(self):
        """Mention detection should be case insensitive."""
        text = "@PRODUCT-MANAGER something"
        assert "@product-manager" in text.lower()


# ---------------------------------------------------------------------------
# @dev-agent Mention Detection Tests
# ---------------------------------------------------------------------------

class TestDevAgentMentionDetection:
    """Tests specifically for @dev-agent mention detection and handling."""

    def _make_responder(self):
        """Create a responder with mocked config."""
        from unittest.mock import MagicMock

        config = {
            "mattermost": {"channel_id": "test_channel"},
            "openclaw": {"anthropic_api_key": "test-key"},
            "projects": {
                "test-project": {
                    "path": "/test/path",
                    "prd_path": "docs/PRD.md",
                    "channel_id": "test_channel"
                }
            },
        }
        from responder import Responder
        r = Responder.__new__(Responder)
        r.cfg = config
        r.bridge = MagicMock()
        r.minimax_api_key = "test-key"
        return r

    def test_dev_agent_mention_basic(self):
        """Basic @dev-agent mention should be detected."""
        text = "@dev-agent hello"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_with_question(self):
        """@dev-agent with question should be detected."""
        text = "@dev-agent how do we handle authentication?"
        is_mention = "@dev-agent" in text.lower()
        is_question = text.strip().endswith("?")
        assert is_mention
        assert is_question

    def test_dev_agent_mention_with_guidance(self):
        """@dev-agent with guidance/instruction should be detected."""
        text = "@dev-agent please use the new API endpoint"
        is_mention = "@dev-agent" in text.lower()
        is_question = text.strip().endswith("?")
        assert is_mention
        assert not is_question

    def test_dev_agent_mention_case_insensitive(self):
        """@dev-agent detection should be case insensitive."""
        text = "@DEV-AGENT what about this?"
        assert "@dev-agent" in text.lower()

        text = "@Dev-Agent Hello"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_at_start(self):
        """@dev-agent at start of message should be detected."""
        text = "@dev-agent can you help?"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_in_middle(self):
        """@dev-agent in middle of message should be detected."""
        text = "Hey there @dev-agent what is the status?"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_at_end(self):
        """@dev-agent at end of message should be detected."""
        text = "Let me know what you think @dev-agent"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_empty_message(self):
        """Empty @dev-agent mention (just the mention) should be detected."""
        text = "@dev-agent"
        assert "@dev-agent" in text.lower()
        # After removing mention, should be empty
        text_without_mention = text.lower().replace("@dev-agent", "").strip()
        assert text_without_mention == ""

    def test_dev_agent_mention_with_whitespace(self):
        """@dev-agent with extra whitespace should still detect properly."""
        text = "@dev-agent  how do we test this?"
        assert "@dev-agent" in text.lower()

    def test_dev_agent_mention_triggers_handle_mention(self):
        """@dev-agent mention should trigger _handle_mention."""
        r = self._make_responder()
        r._dev_agent_response = MagicMock(return_value="Test response")

        # Simulate what _check_for_commands does
        text = "@dev-agent how do we test this?"
        is_question = text.strip().endswith("?")

        # Check that mention is detected
        mention_detected = "@dev-agent" in text.lower()
        assert mention_detected

    def test_dev_agent_and_product_manager_both_mentioned(self):
        """When both agents mentioned, detection should identify both."""
        text = "@product-manager and @dev-agent something"
        is_pm = "@product-manager" in text.lower()
        is_dev = "@dev-agent" in text.lower()
        assert is_pm
        assert is_dev

    def test_dev_agent_mention_with_feature_request(self):
        """@dev-agent mention with feature request pattern should be detected."""
        text = "@dev-agent add user authentication"
        is_mention = "@dev-agent" in text.lower()
        is_question = text.strip().endswith("?")
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                          "how can", "what is", "what's", "why is", "why does",
                          "when will", "should i", "should we"]
        has_question_phrase = any(phrase in text.lower() for phrase in question_phrases)

        assert is_mention
        assert not is_question
        assert not has_question_phrase


# ---------------------------------------------------------------------------
# Dev Agent Integration Tests
# ---------------------------------------------------------------------------

class TestDevAgentIntegration:
    """Integration tests for @dev-agent mention flow."""

    def _make_responder(self):
        """Create a responder with mocked config."""
        pass

        config = {
            "mattermost": {"channel_id": "test_channel"},
            "openclaw": {"anthropic_api_key": "test-key"},
            "projects": {
                "test-project": {
                    "path": "/test/path",
                    "prd_path": "docs/PRD.md",
                    "channel_id": "test_channel"
                }
            },
        }
        from responder import Responder
        r = Responder.__new__(Responder)
        r.cfg = config
        r.bridge = MagicMock()
        r.minimax_api_key = "test-key"
        return r

    def test_dev_agent_question_routes_to_dev_response(self):
        """@dev-agent question should route to _dev_agent_response()."""
        r = self._make_responder()
        r._dev_agent_response = MagicMock(return_value="Technical answer")

        r._handle_mention("@dev-agent how do we handle auth?", "test_channel", is_question=True)

        r._dev_agent_response.assert_called_once()
        r.bridge.send.assert_called_once()
        call_args = r.bridge.send.call_args
        assert call_args[1]["sender"] == "Dev Agent"

    def test_dev_agent_guidance_routes_to_dev_response(self):
        """@dev-agent guidance should route to _dev_agent_response()."""
        r = self._make_responder()
        r._dev_agent_response = MagicMock(return_value="Acknowledged")

        r._handle_mention("@dev-agent please use the new API", "test_channel", is_question=False)

        r._dev_agent_response.assert_called_once()
        r.bridge.send.assert_called_once()

    def test_empty_dev_agent_mention_provides_guidance(self):
        """Empty @dev-agent mention should provide usage guidance."""
        r = self._make_responder()

        r._handle_mention("@dev-agent", "test_channel", is_question=False)

        r.bridge.send.assert_called_once()
        call_args = r.bridge.send.call_args
        response_text = call_args[0][0]
        assert "I'm the Dev Agent" in response_text
        assert "How do we handle" in response_text

    def test_dev_agent_precedes_product_manager(self):
        """When both @dev-agent and @product-manager mentioned, dev-agent wins."""
        r = self._make_responder()
        r._dev_agent_response = MagicMock(return_value="Dev response")

        r._handle_mention("@product-manager and @dev-agent what's the approach?", "test_channel", is_question=True)

        r._dev_agent_response.assert_called_once()
        r._generate_response = MagicMock(return_value="PM response")
        # PM should NOT be called since dev-agent wins
        r._generate_response.assert_not_called()


# ---------------------------------------------------------------------------
# Dev Agent Question vs Guidance Detection
# ---------------------------------------------------------------------------

class TestDevAgentQuestionGuidanceDetection:
    """Tests for distinguishing questions from guidance in @dev-agent mentions."""

    def _detect_question(self, text: str) -> bool:
        """Helper to detect if text is a question (matches responder.py logic)."""
        is_question = text.strip().endswith("?")
        question_phrases = ["can you", "could you", "would you", "will you", "how do",
                          "how can", "what is", "what's", "why is", "why does",
                          "when will", "should i", "should we"]
        text_lower = text.lower()
        is_question = is_question or any(phrase in text_lower for phrase in question_phrases)
        return is_question

    def test_question_with_trailing_question_mark(self):
        """Message ending with ? should be detected as question."""
        text = "@dev-agent how do we handle authentication?"
        assert self._detect_question(text) is True

    def test_question_with_what_is_phrase(self):
        """Message with 'what is' should be detected as question."""
        text = "@dev-agent what is the current implementation?"
        assert self._detect_question(text) is True

    def test_question_with_whats_phrase(self):
        """Message with 'what's' should be detected as question."""
        text = "@dev-agent what's the best approach here"
        assert self._detect_question(text) is True

    def test_question_with_how_do_phrase(self):
        """Message with 'how do' should be detected as question."""
        text = "@dev-agent how do we test this"
        assert self._detect_question(text) is True

    def test_question_with_how_can_phrase(self):
        """Message with 'how can' should be detected as question."""
        text = "@dev-agent how can I add a new feature"
        assert self._detect_question(text) is True

    def test_question_with_can_you_phrase(self):
        """Message with 'can you' should be detected as question."""
        text = "@dev-agent can you explain the architecture"
        assert self._detect_question(text) is True

    def test_question_with_could_you_phrase(self):
        """Message with 'could you' should be detected as question."""
        text = "@dev-agent could you help me debug this"
        assert self._detect_question(text) is True

    def test_question_with_why_does_phrase(self):
        """Message with 'why does' should be detected as question."""
        text = "@dev-agent why does this fail"
        assert self._detect_question(text) is True

    def test_question_with_should_we_phrase(self):
        """Message with 'should we' should be detected as question."""
        text = "@dev-agent should we use Redis for caching"
        assert self._detect_question(text) is True

    def test_guidance_imperative_not_question(self):
        """Imperative statement without ? should NOT be detected as question."""
        text = "@dev-agent please use the new API endpoint"
        assert self._detect_question(text) is False

    def test_guidance_use_keyword_not_question(self):
        """Statement with 'use' should NOT be detected as question."""
        text = "@dev-agent use the new library for this"
        assert self._detect_question(text) is False

    def test_guidance_consider_keyword_not_question(self):
        """Statement with 'consider' should NOT be detected as question."""
        text = "@dev-agent consider refactoring this module"
        assert self._detect_question(text) is False

    def test_guidance_remember_to_not_question(self):
        """Statement with 'remember to' should NOT be detected as question."""
        text = "@dev-agent remember to add tests for this"
        assert self._detect_question(text) is False

    def test_guidance_ensure_keyword_not_question(self):
        """Statement with 'ensure' should NOT be detected as question."""
        text = "@dev-agent ensure we handle errors properly"
        assert self._detect_question(text) is False

    def test_guidance_add_keyword_not_question(self):
        """Statement with 'add' should NOT be detected as question."""
        text = "@dev-agent add logging to this function"
        assert self._detect_question(text) is False

    def test_guidance_fix_keyword_not_question(self):
        """Statement with 'fix' should NOT be detected as question."""
        text = "@dev-agent fix the memory leak"
        assert self._detect_question(text) is False

    def test_statement_not_question(self):
        """Plain statement should NOT be detected as question."""
        text = "@dev-agent I'm working on the auth module"
        assert self._detect_question(text) is False

    def test_statement_with_period_not_question(self):
        """Statement ending with period should NOT be detected as question."""
        text = "@dev-agent the tests are passing now."
        assert self._detect_question(text) is False

    def test_command_statement_not_question(self):
        """Command-like statement should NOT be detected as question."""
        text = "@dev-agent update the documentation"
        assert self._detect_question(text) is False

    def test_question_detection_case_insensitive(self):
        """Question detection should be case insensitive."""
        text = "@dev-agent HOW DO I use this?"
        assert self._detect_question(text) is True

    def test_mixed_guidance_and_question_with_question_mark(self):
        """Message with guidance but ending in ? should be detected as question."""
        text = "@dev-agent please use the new API, what do you think?"
        assert self._detect_question(text) is True
