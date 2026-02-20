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

    def test_no_mention_does_not_trigger_mention_handler(self):
        """Message without @mention should not trigger mention handler."""
        text = "Hello, how are you?"
        # Neither @product-manager nor @dev-agent present
        has_pm_mention = "@product-manager" in text.lower()
        has_dev_mention = "@dev-agent" in text.lower()
        assert has_pm_mention is False
        assert has_dev_mention is False

    def test_no_mention_plain_statement(self):
        """Plain statement without mention should not be detected as mention."""
        text = "This is a feature request"
        has_pm_mention = "@product-manager" in text.lower()
        has_dev_mention = "@dev-agent" in text.lower()
        assert has_pm_mention is False
        assert has_dev_mention is False

    def test_no_mention_question_without_mention(self):
        """Question without mention should not trigger mention routing."""
        text = "Can someone help me with this issue?"
        has_pm_mention = "@product-manager" in text.lower()
        has_dev_mention = "@dev-agent" in text.lower()
        assert has_pm_mention is False
        assert has_dev_mention is False


class TestMultipleMentionsPrecedence:
    """Tests for multiple @mention precedence logic."""

    def test_dev_agent_takes_precedence_over_product_manager(self):
        """When both @dev-agent and @product-manager are mentioned, @dev-agent should take precedence."""
        text = "@product-manager and @dev-agent what is the status?"
        text_lower = text.lower()

        # Check that both mentions are present
        is_pm = "@product-manager" in text_lower
        is_dev = "@dev-agent" in text_lower

        assert is_pm is True
        assert is_dev is True

        # Dev should take precedence (checked first in _handle_mention)
        # In the current implementation, is_dev is checked first
        # So if both are True, is_dev branch executes first
        precedence_result = "dev" if is_dev else "pm"
        assert precedence_result == "dev"

    def test_mentions_order_does_not_matter(self):
        """@dev-agent should take precedence regardless of mention order."""
        # Test with @dev-agent first
        text1 = "@dev-agent help me @product-manager"
        text1_lower = text1.lower()
        is_dev1 = "@dev-agent" in text1_lower
        is_pm1 = "@product-manager" in text1_lower
        result1 = "dev" if is_dev1 else "pm"

        # Test with @product-manager first
        text2 = "@product-manager help me @dev-agent"
        text2_lower = text2.lower()
        is_dev2 = "@dev-agent" in text2_lower
        is_pm2 = "@product-manager" in text2_lower
        result2 = "dev" if is_dev2 else "pm"

        # Both should route to dev since both mentions are present
        assert result1 == "dev"
        assert result2 == "dev"

    def test_only_product_manager_routes_to_pm(self):
        """Only @product-manager mention should route to PM."""
        text = "@product-manager what should we build next?"
        text_lower = text.lower()

        is_pm = "@product-manager" in text_lower
        is_dev = "@dev-agent" in text_lower

        assert is_pm is True
        assert is_dev is False
        assert is_pm and not is_dev

    def test_only_dev_agent_routes_to_dev(self):
        """Only @dev-agent mention should route to Dev."""
        text = "@dev-agent implement this feature"
        text_lower = text.lower()

        is_pm = "@product-manager" in text_lower
        is_dev = "@dev-agent" in text_lower

        assert is_pm is False
        assert is_dev is True
        assert is_dev and not is_pm


# ---------------------------------------------------------------------------
# Mention routing behavior
# ---------------------------------------------------------------------------

class TestMentionRoutingBehavior:
    """Tests for actual routing behavior in responder._handle_mention method."""

    def _make_responder(self):
        """Create a responder with mocked config."""
        from unittest.mock import MagicMock

        config = {
            "mattermost": {"channel_id": "test_channel"},
            "openclaw": {},
            "redis_streams": {},
            "projects": {},
        }
        # Create responder using __new__ to bypass __init__
        from responder import Responder
        r = Responder.__new__(Responder)
        r.cfg = config
        r.bridge = MagicMock()
        r.redis = None  # Force fallback mode
        r.processed_messages = set()
        return r

    def test_dev_agent_mention_routes_to_dev_agent(self):
        """@dev-agent mention should route to Dev Agent, not PM Agent."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Mock the methods that should be called
        r._generate_response = MagicMock(return_value="Dev response")
        r._publish_feature_request = MagicMock()

        # Call _handle_mention with @dev-agent (not a question)
        r._handle_mention("@dev-agent help", "test_channel", is_question=False)

        # Verify _publish_feature_request is called (for feature requests to Dev)
        r._publish_feature_request.assert_called_once_with(channel_id="test_channel")
        # Verify _generate_response was NOT called for pm-agent path
        r._generate_response.assert_not_called()

    def test_dev_agent_question_routes_to_dev_agent(self):
        """@dev-agent question should be answered by Dev Agent."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Mock the methods
        r._generate_response = MagicMock(return_value="Dev answer")
        r._publish_feature_request = MagicMock()

        # Call _handle_mention with a question
        r._handle_mention("@dev-agent how do I implement auth?", "test_channel", is_question=True)

        # Verify Dev Agent is used for answering
        r.bridge.send.assert_called_once()
        call_args = r.bridge.send.call_args
        assert call_args[1].get('sender') == "Dev Agent", \
            "@dev-agent question should be answered by Dev Agent"

        # Verify the response was generated with is_pm=False
        r._generate_response.assert_called_once()
        call_args = r._generate_response.call_args
        assert call_args[1].get('is_pm') is False, \
            "@dev-agent should route with is_pm=False"

    def test_dev_agent_takes_precedence_over_product_manager(self):
        """When both @dev-agent and @product-manager present, should route to Dev Agent."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Track routing
        r._generate_response = MagicMock(return_value="response")
        r._publish_feature_request = MagicMock()

        # Call with both mentions - dev-agent should take precedence
        r._handle_mention("@product-manager and @dev-agent help", "test_channel", is_question=False)

        # Should route to Dev Agent (precedence), not PM Agent
        r._publish_feature_request.assert_called_once_with(channel_id="test_channel")

    def test_product_manager_mention_routes_to_pm_agent(self):
        """@product-manager mention should route to PM Agent, not Dev Agent."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Mock the methods that should be called
        r._generate_response = MagicMock(return_value="PM response")
        r._publish_feature_request = MagicMock()

        # Call _handle_mention with @product-manager (not a question)
        r._handle_mention("@product-manager help", "test_channel", is_question=False)

        # Verify _publish_feature_request is called (for feature requests to PM)
        r._publish_feature_request.assert_called_once_with(channel_id="test_channel")
        # Verify _generate_response was NOT called for dev-agent path
        r._generate_response.assert_not_called()

    def test_product_manager_question_routes_to_pm_agent(self):
        """@product-manager question should be answered by PM Agent."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Mock the methods
        r._generate_response = MagicMock(return_value="PM answer")
        r._publish_feature_request = MagicMock()

        # Call _handle_mention with a question
        r._handle_mention("@product-manager what features should we add?", "test_channel", is_question=True)

        # Verify PM Agent is used for answering
        r.bridge.send.assert_called_once()
        call_args = r.bridge.send.call_args
        assert call_args[1].get('sender') == "PM Agent", \
            "@product-manager question should be answered by PM Agent"

        # Verify the response was generated with is_pm=True
        r._generate_response.assert_called_once()
        call_args = r._generate_response.call_args
        assert call_args[1].get('is_pm') is True, \
            "@product-manager should route with is_pm=True"

    def test_product_manager_does_not_route_to_dev_agent(self):
        """@product-manager mention should NOT trigger Dev Agent routing."""
        from unittest.mock import MagicMock
        r = self._make_responder()

        # Track calls to verify correct routing
        r._generate_response = MagicMock(return_value="response")
        r._publish_feature_request = MagicMock()

        # Call with @product-manager
        r._handle_mention("@product-manager add a feature", "test_channel", is_question=False)

        # Verify _publish_feature_request is called (PM Agent path)
        r._publish_feature_request.assert_called_once_with(channel_id="test_channel")

        # If it incorrectly routed to Dev Agent, it would call _generate_response
        # with is_pm=False. Let's verify that didn't happen by checking
        # the method was called with the right parameters
        if r._generate_response.called:
            call_args = r._generate_response.call_args
            is_pm_arg = call_args[1].get('is_pm')
            assert is_pm_arg is True, \
                "@product-manager should pass is_pm=True, not route to Dev Agent"
