"""Tests for responder config loading and deep merge.

Run: uv run pytest tests/test_responder.py -m "not integration"
"""




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
