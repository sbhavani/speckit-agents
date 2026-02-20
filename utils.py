"""Shared utility functions for speckit-agents."""


def deep_merge(base: dict, override: dict) -> None:
    """Merge override dict into base dict in-place (recursive)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
