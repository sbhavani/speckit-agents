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

    def _key(self, project_path: str) -> str:
        """Generate Redis key for a project."""
        # Use just the dirname to keep keys short
        import os
        return f"{self.prefix}:state:{os.path.basename(project_path)}"

    def save(self, project_path: str, state: dict) -> None:
        """Save state to Redis."""
        key = self._key(project_path)
        self.redis.set(key, json.dumps(state), ex=86400)  # 24h expiry
        logger.debug(f"State saved to Redis: {key}")

    def load(self, project_path: str) -> Optional[dict]:
        """Load state from Redis."""
        key = self._key(project_path)
        data = self.redis.get(key)
        if data:
            logger.debug(f"State loaded from Redis: {key}")
            return json.loads(data)
        return None

    def delete(self, project_path: str) -> None:
        """Delete state from Redis."""
        key = self._key(project_path)
        self.redis.delete(key)
        logger.debug(f"State deleted from Redis: {key}")
