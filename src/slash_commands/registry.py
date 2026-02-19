"""Mattermost slash command registry."""

import json
import logging
import subprocess
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0


class SlashCommandRegistry:
    """Registry for managing Mattermost slash commands."""

    def __init__(
        self,
        mattermost_url: str = "http://localhost:8065",
        bot_token: str = "",
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_delay: float = DEFAULT_INITIAL_DELAY,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ):
        self.mattermost_url = mattermost_url.rstrip("/")
        self.bot_token = bot_token
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    def _execute_with_retry(
        self,
        cmd: list[str],
        retries: Optional[int] = None,
    ) -> tuple[int, str, str]:
        """Execute a curl command with retry logic for rate limits.

        Args:
            cmd: The curl command to execute
            retries: Number of retries (defaults to self.max_retries)

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        max_retries = retries if retries is not None else self.max_retries
        delay = self.initial_delay

        for attempt in range(max_retries + 1):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Check for rate limit (429)
            if result.returncode != 0:
                # Check stderr for rate limit indicators
                stderr_lower = result.stderr.lower()
                if "429" in stderr_lower or "rate limit" in stderr_lower:
                    if attempt < max_retries:
                        logger.warning(
                            f"Rate limited by Mattermost API, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                        delay *= self.backoff_factor
                        continue

            return result.returncode, result.stdout, result.stderr

        # Final attempt failed
        return result.returncode, result.stdout, result.stderr

    def register_command(
        self,
        trigger: str,
        callback_url: str,
        description: str = "",
        username: str = "agent-team",
        icon_url: str = "",
    ) -> dict[str, Any]:
        """Register a slash command with Mattermost.

        Args:
            trigger: Command trigger (without leading slash)
            callback_url: URL Mattermost calls when command is invoked
            description: Human-readable description
            username: Override username for responses
            icon_url: Override icon for responses

        Returns:
            Response from Mattermost API
        """
        if not self.bot_token:
            logger.warning("No bot token configured, skipping registration")
            return {"error": "no_token"}

        payload = {
            "command": f"/{trigger}",
            "url": callback_url,
            "method": "POST",
            "username": username,
            "description": description or f"Agent Team {trigger} command",
        }

        if icon_url:
            payload["icon_url"] = icon_url

        # Use curl to call Mattermost API
        cmd = [
            "curl", "-sf",
            "-X", "POST",
            f"{self.mattermost_url}/api/v4/commands",
            "-H", f"Authorization: Bearer {self.bot_token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ]

        try:
            returncode, stdout, stderr = self._execute_with_retry(cmd)

            if returncode != 0:
                logger.error(f"Failed to register command: {stderr}")
                return {"error": stderr}

            return json.loads(stdout)
        except Exception as e:
            logger.error(f"Error registering command: {e}")
            return {"error": str(e)}

    def list_commands(self, team_id: str = "") -> list[dict[str, Any]]:
        """List registered slash commands.

        Args:
            team_id: Optional team ID to filter by

        Returns:
            List of registered commands
        """
        if not self.bot_token:
            return []

        url = f"{self.mattermost_url}/api/v4/commands"
        if team_id:
            url += f"?team_id={team_id}"

        cmd = [
            "curl", "-sf",
            url,
            "-H", f"Authorization: Bearer {self.bot_token}",
        ]

        try:
            returncode, stdout, stderr = self._execute_with_retry(cmd)

            if returncode != 0:
                logger.warning(f"Failed to list commands: {stderr}")
                return []

            return json.loads(stdout)
        except Exception as e:
            logger.error(f"Error listing commands: {e}")
            return []

    def delete_command(self, command_id: str) -> bool:
        """Delete a registered slash command.

        Args:
            command_id: Command ID to delete

        Returns:
            True if successful
        """
        if not self.bot_token:
            return False

        cmd = [
            "curl", "-sf",
            "-X", "DELETE",
            f"{self.mattermost_url}/api/v4/commands/{command_id}",
            "-H", f"Authorization: Bearer {self.bot_token}",
        ]

        try:
            returncode, stdout, stderr = self._execute_with_retry(cmd)
            return returncode == 0
        except Exception as e:
            logger.error(f"Error deleting command: {e}")
            return False
