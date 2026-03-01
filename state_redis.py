"""Redis-backed state storage for orchestrator.

This provides faster state persistence compared to file-based storage.
"""

import json
import logging
from typing import Optional

import redis

logger = logging.getLogger(__name__)


class RedisState:
    """Store workflow state in Redis instead of files."""

    def __init__(self, redis_url: str = "redis://localhost:6379", prefix: str = "agent-team"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix

    def _key(self, project_path: str, channel_id: str = "") -> str:
        """Generate Redis key for a project."""
        # Use project name + channel_id for stable key across worktrees
        import os
        project_name = os.path.basename(project_path)
        # Remove timestamp suffix if present (from worktree)
        project_name = project_name.split("-")[0] if project_name.split("-")[0] else project_name
        if channel_id:
            return f"{self.prefix}:state:{project_name}:{channel_id}"
        return f"{self.prefix}:state:{project_name}"

    def save(self, project_path: str, state: dict, channel_id: str = "") -> None:
        """Save state to Redis."""
        key = self._key(project_path, channel_id)
        self.redis.set(key, json.dumps(state), ex=86400)  # 24h expiry
        logger.debug(f"State saved to Redis: {key}")

    def load(self, project_path: str, channel_id: str = "") -> Optional[dict]:
        """Load state from Redis."""
        key = self._key(project_path, channel_id)
        data = self.redis.get(key)
        if data:
            logger.debug(f"State loaded from Redis: {key}")
            return json.loads(data)
        return None

    def delete(self, project_path: str, channel_id: str = "") -> None:
        """Delete state from Redis."""
        key = self._key(project_path, channel_id)
        self.redis.delete(key)
        logger.debug(f"State deleted from Redis: {key}")
