"""Unit tests for ScalingConfig validation."""

import pytest
from src.scaling.config import ScalingConfig


class TestScalingConfigValidation:
    """Tests for ScalingConfig validation."""

    def test_default_values(self):
        """Test that default values are valid."""
        config = ScalingConfig()

        assert config.enabled is False
        assert config.min_workers == 1
        assert config.max_workers == 10
        assert config.scale_up_threshold == 2.0
        assert config.scale_down_threshold == 0.25
        assert config.scale_cooldown == 60
        assert config.idle_timeout == 300
        assert config.poll_interval == 10

    def test_min_workers_must_be_at_least_one(self):
        """Test that min_workers must be >= 1."""
        with pytest.raises(ValueError, match="min_workers must be >= 1"):
            ScalingConfig(min_workers=0)

        with pytest.raises(ValueError, match="min_workers must be >= 1"):
            ScalingConfig(min_workers=-1)

        # Valid case
        config = ScalingConfig(min_workers=1)
        assert config.min_workers == 1

    def test_max_workers_must_be_at_least_min_workers(self):
        """Test that max_workers must be >= min_workers."""
        with pytest.raises(ValueError, match="max_workers must be >= min_workers"):
            ScalingConfig(min_workers=5, max_workers=4)

        with pytest.raises(ValueError, match="max_workers must be >= min_workers"):
            ScalingConfig(min_workers=3, max_workers=0)

        # Valid case
        config = ScalingConfig(min_workers=2, max_workers=5)
        assert config.min_workers == 2
        assert config.max_workers == 5

    def test_scale_up_threshold_must_be_greater_than_scale_down_threshold(self):
        """Test that scale_up_threshold must be > scale_down_threshold."""
        with pytest.raises(
            ValueError, match="scale_up_threshold must be > scale_down_threshold"
        ):
            ScalingConfig(scale_up_threshold=0.5, scale_down_threshold=0.5)

        with pytest.raises(
            ValueError, match="scale_up_threshold must be > scale_down_threshold"
        ):
            ScalingConfig(scale_up_threshold=0.1, scale_down_threshold=0.25)

        # Valid case
        config = ScalingConfig(scale_up_threshold=2.0, scale_down_threshold=0.25)
        assert config.scale_up_threshold == 2.0
        assert config.scale_down_threshold == 0.25

    def test_scale_cooldown_must_be_at_least_10(self):
        """Test that scale_cooldown must be >= 10."""
        with pytest.raises(ValueError, match="scale_cooldown must be >= 10"):
            ScalingConfig(scale_cooldown=5)

        with pytest.raises(ValueError, match="scale_cooldown must be >= 10"):
            ScalingConfig(scale_cooldown=9)

        # Valid case
        config = ScalingConfig(scale_cooldown=10)
        assert config.scale_cooldown == 10

    def test_idle_timeout_must_be_at_least_60(self):
        """Test that idle_timeout must be >= 60."""
        with pytest.raises(ValueError, match="idle_timeout must be >= 60"):
            ScalingConfig(idle_timeout=30)

        with pytest.raises(ValueError, match="idle_timeout must be >= 60"):
            ScalingConfig(idle_timeout=59)

        # Valid case
        config = ScalingConfig(idle_timeout=60)
        assert config.idle_timeout == 60

    def test_poll_interval_must_be_at_least_one(self):
        """Test that poll_interval must be >= 1."""
        with pytest.raises(ValueError, match="poll_interval must be >= 1"):
            ScalingConfig(poll_interval=0)

        with pytest.raises(ValueError, match="poll_interval must be >= 1"):
            ScalingConfig(poll_interval=-1)

        # Valid case
        config = ScalingConfig(poll_interval=1)
        assert config.poll_interval == 1


class TestScalingConfigFromDict:
    """Tests for ScalingConfig.from_dict method."""

    def test_from_dict_with_none(self):
        """Test creating config from None returns defaults."""
        config = ScalingConfig.from_dict(None)
        assert config.enabled is False
        assert config.min_workers == 1

    def test_from_dict_with_empty_dict(self):
        """Test creating config from empty dict returns defaults."""
        config = ScalingConfig.from_dict({})
        assert config.enabled is False
        assert config.min_workers == 1

    def test_from_dict_with_valid_data(self):
        """Test creating config from valid dictionary."""
        data = {
            "enabled": True,
            "min_workers": 2,
            "max_workers": 8,
            "scale_up_threshold": 3.0,
            "scale_down_threshold": 0.5,
            "scale_cooldown": 30,
            "idle_timeout": 120,
            "poll_interval": 5,
        }
        config = ScalingConfig.from_dict(data)

        assert config.enabled is True
        assert config.min_workers == 2
        assert config.max_workers == 8
        assert config.scale_up_threshold == 3.0
        assert config.scale_down_threshold == 0.5
        assert config.scale_cooldown == 30
        assert config.idle_timeout == 120
        assert config.poll_interval == 5

    def test_from_dict_with_partial_data(self):
        """Test creating config from partial dictionary."""
        data = {"enabled": True, "min_workers": 3}
        config = ScalingConfig.from_dict(data)

        assert config.enabled is True
        assert config.min_workers == 3
        # Other values should be defaults
        assert config.max_workers == 10

    def test_from_dict_filters_unknown_fields(self):
        """Test that unknown fields are filtered out."""
        data = {
            "enabled": True,
            "unknown_field": "should_be_ignored",
            "another_unknown": 123,
        }
        config = ScalingConfig.from_dict(data)

        assert config.enabled is True
        # Should not raise, unknown fields are ignored


class TestScalingConfigToDict:
    """Tests for ScalingConfig.to_dict method."""

    def test_to_dict_returns_all_fields(self):
        """Test that to_dict returns all configuration fields."""
        config = ScalingConfig(
            enabled=True,
            min_workers=2,
            max_workers=8,
            scale_up_threshold=3.0,
            scale_down_threshold=0.5,
            scale_cooldown=30,
            idle_timeout=120,
            poll_interval=5,
        )
        result = config.to_dict()

        assert result == {
            "enabled": True,
            "min_workers": 2,
            "max_workers": 8,
            "scale_up_threshold": 3.0,
            "scale_down_threshold": 0.5,
            "scale_cooldown": 30,
            "idle_timeout": 120,
            "poll_interval": 5,
        }

    def test_to_dict_with_defaults(self):
        """Test to_dict with default values."""
        config = ScalingConfig()
        result = config.to_dict()

        assert result["enabled"] is False
        assert result["min_workers"] == 1
        assert result["max_workers"] == 10
        assert result["scale_up_threshold"] == 2.0
        assert result["scale_down_threshold"] == 0.25
        assert result["scale_cooldown"] == 60
        assert result["idle_timeout"] == 300
        assert result["poll_interval"] == 10


class TestScalingConfigRoundTrip:
    """Tests for round-trip conversion (from_dict -> to_dict)."""

    def test_round_trip_with_custom_values(self):
        """Test that config can be converted to dict and back."""
        original = ScalingConfig(
            enabled=True,
            min_workers=3,
            max_workers=7,
            scale_up_threshold=2.5,
            scale_down_threshold=0.3,
            scale_cooldown=45,
            idle_timeout=180,
            poll_interval=8,
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = ScalingConfig.from_dict(data)

        assert restored.enabled == original.enabled
        assert restored.min_workers == original.min_workers
        assert restored.max_workers == original.max_workers
        assert restored.scale_up_threshold == original.scale_up_threshold
        assert restored.scale_down_threshold == original.scale_down_threshold
        assert restored.scale_cooldown == original.scale_cooldown
        assert restored.idle_timeout == original.idle_timeout
        assert restored.poll_interval == original.poll_interval


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
