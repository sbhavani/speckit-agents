"""Redis-backed state storage for orchestrator.

This provides faster state persistence compared to file-based storage.
"""

import json
import logging
from typing import Optional, Tuple

import redis

logger = logging.getLogger(__name__)

# Required state fields and their expected types
REQUIRED_STATE_FIELDS = {
    "version": int,
    "workflow_type": str,
    "phase": str,
    "feature": (dict, type(None)),
    "pm_session": (str, type(None)),
    "dev_session": (str, type(None)),
    "pr_url": (str, type(None)),
    "branch_name": (str, type(None)),
    "worker_handoff": bool,
    "original_path": str,
    "worktree_path": (str, type(None)),
    "thread_root_id": (str, type(None)),
    "started_at": str,
    "updated_at": str,
}


class RedisState:
    """Store workflow state in Redis instead of files."""

    def __init__(self, redis_url: str = "redis://localhost:6379", prefix: str = "agent-team"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix

    def _key(self, project_path: str) -> str:
        """Generate Redis key for a project."""
        # Use just the dirname to keep keys short
        import os
        return f"{self.prefix}:state:{os.path.basename(project_path)}"

    def _backup_key(self, project_path: str) -> str:
        """Generate Redis key for state backup."""
        return f"{self._key(project_path)}:backup"

    def load_backup(self, project_path: str) -> Optional[dict]:
        """Load state from backup in Redis.

        Returns:
            Valid state dict from backup, or None if backup is missing/invalid
        """
        key = self._backup_key(project_path)
        try:
            data = self.redis.get(key)
            if data:
                logger.debug(f"Backup state loaded from Redis: {key}")
                return json.loads(data)
            return None
        except redis.RedisError as e:
            logger.error("Failed to load backup from Redis: %s", e)
            return None
        except json.JSONDecodeError as e:
            logger.warning("Backup state corrupted (invalid JSON) in Redis: %s", e)
            return None

    def save(self, project_path: str, state: dict) -> None:
        """Save state to Redis, creating backup of previous state first."""
        key = self._key(project_path)
        backup_key = self._backup_key(project_path)

        try:
            # Create backup of current state before overwriting
            current_data = self.redis.get(key)
            if current_data:
                # Store current state as backup before saving new state
                self.redis.set(backup_key, current_data, ex=86400)
                logger.debug(f"State backup created: {backup_key}")

            # Save new state
            self.redis.set(key, json.dumps(state), ex=86400)
            logger.debug(f"State saved to Redis: {key}")
        except redis.RedisError as e:
            logger.error("Failed to save state to Redis: %s", e)
            raise

    def load(self, project_path: str) -> Optional[dict]:
        """Load state from Redis."""
        key = self._key(project_path)
        try:
            data = self.redis.get(key)
            if data:
                logger.debug(f"State loaded from Redis: {key}")
                return json.loads(data)
            return None
        except redis.RedisError as e:
            logger.error("Failed to load state from Redis: %s", e)
            return None
        except json.JSONDecodeError as e:
            logger.warning("State corrupted (invalid JSON) in Redis: %s. Cannot resume.", e)
            return None

    def _validate_state(self, data: dict) -> Tuple[bool, Optional[str]]:
        """Validate state structure.

        Returns:
            (True, None) if valid
            (False, error_message) if invalid
        """
        # Check required fields
        missing_fields = [f for f in REQUIRED_STATE_FIELDS if f not in data]
        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"

        # Check version
        if data.get("version") != 1:
            return False, f"Invalid version: {data.get('version')} (expected 1)"

        # Check phase is valid (will be validated by caller with Phase enum)
        if "phase" not in data or not isinstance(data["phase"], str):
            return False, f"Invalid phase: {data.get('phase')} (expected string)"

        # Check field types
        for field, expected_types in REQUIRED_STATE_FIELDS.items():
            value = data.get(field)
            if not isinstance(expected_types, tuple):
                expected_types = (expected_types,)
            if not isinstance(value, expected_types):
                return False, f"Invalid type for {field}: {type(value).__name__} (expected {expected_types})"

        return True, None

    def load_validated(self, project_path: str) -> Tuple[Optional[dict], Optional[str]]:
        """Load state from Redis and validate its structure.

        Returns:
            (state_dict, None) if valid
            (None, error_message) if invalid or missing
        """
        data = self.load(project_path)
        if data is None:
            return None, "No state found in Redis"

        is_valid, error_msg = self._validate_state(data)
        if not is_valid:
            logger.warning("State corrupted (invalid structure) in Redis: %s", error_msg)
            return None, error_msg

        logger.info("State loaded and validated from Redis: phase=%s", data.get("phase"))
        return data, None

    def delete(self, project_path: str) -> None:
        """Delete state from Redis."""
        key = self._key(project_path)
        try:
            self.redis.delete(key)
            logger.debug(f"State deleted from Redis: {key}")
        except redis.RedisError as e:
            logger.error("Failed to delete state from Redis: %s", e)
            raise
