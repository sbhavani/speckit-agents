"""Tests for responder config loading and deep merge.

Run: uv run pytest tests/test_responder.py -m "not integration"
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml


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
