"""Scaling configuration model."""

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class ScalingConfig:
    """Configuration for dynamic worker pool scaling."""

    enabled: bool = False
    min_workers: int = 1
    max_workers: int = 10
    scale_up_threshold: float = 2.0
    scale_down_threshold: float = 0.25
    scale_cooldown: int = 60
    idle_timeout: int = 300
    poll_interval: int = 10

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self._validate()

    def _validate(self) -> None:
        """Validate scaling configuration."""
        if self.min_workers < 1:
            raise ValueError("min_workers must be >= 1")
        if self.max_workers < self.min_workers:
            raise ValueError("max_workers must be >= min_workers")
        if self.scale_up_threshold <= self.scale_down_threshold:
            raise ValueError("scale_up_threshold must be > scale_down_threshold")
        if self.scale_cooldown < 10:
            raise ValueError("scale_cooldown must be >= 10")
        if self.idle_timeout < 60:
            raise ValueError("idle_timeout must be >= 60")
        if self.poll_interval < 1:
            raise ValueError("poll_interval must be >= 1")

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ScalingConfig":
        """Create ScalingConfig from dictionary.

        Args:
            data: Dictionary with scaling configuration, or None/empty

        Returns:
            ScalingConfig instance
        """
        if not data:
            return cls()

        # Filter to only known fields
        known_fields = {
            "enabled",
            "min_workers",
            "max_workers",
            "scale_up_threshold",
            "scale_down_threshold",
            "scale_cooldown",
            "idle_timeout",
            "poll_interval",
        }
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_dict(self) -> dict:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "enabled": self.enabled,
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            "scale_up_threshold": self.scale_up_threshold,
            "scale_down_threshold": self.scale_down_threshold,
            "scale_cooldown": self.scale_cooldown,
            "idle_timeout": self.idle_timeout,
            "poll_interval": self.poll_interval,
        }


def load_worker_scaling_config(config_path: str = "config.yaml") -> ScalingConfig:
    """Load worker scaling configuration from YAML config file.

    Args:
        config_path: Path to the YAML configuration file.
                     Defaults to 'config.yaml' in the current directory.
                     If not found, tries the directory containing this module.

    Returns:
        ScalingConfig instance loaded from config file, or default config if
        the file or worker_scaling section is not found.
    """
    # Try current directory first
    paths_to_try = [config_path]

    # Try relative to this module's location
    module_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(module_dir)
    paths_to_try.append(os.path.join(repo_root, config_path))

    # Try the agent-team directory
    paths_to_try.append(os.path.join(repo_root, "config.yaml"))

    config_data = {}
    for path in paths_to_try:
        if os.path.exists(path):
            with open(path, "r") as f:
                full_config = yaml.safe_load(f) or {}
                config_data = full_config.get("worker_scaling", {})
            break

    return ScalingConfig.from_dict(config_data)
