"""Mattermost communication bridge with dual bot identities.

Sends messages via the Mattermost REST API using either:
- Dev Agent bot (for implementation messages)
- PM Agent bot (for product management messages)

Reads messages via the Mattermost REST API.
"""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


class MattermostBridge:
    """Send and receive Mattermost messages via REST API.

    Supports two bot identities: Dev bot and PM bot.
    Human messages are those from neither bot.
    """

    def __init__(
        self,
        channel_id: str,
        mattermost_url: str = "http://localhost:8065",
        dev_bot_token: str = "",
        dev_bot_user_id: str = "",
        pm_bot_token: str = "",
        pm_bot_user_id: str = "",
    ):
        self.channel_id = channel_id
        self.mattermost_url = mattermost_url
        self.dev_bot_token = dev_bot_token
        self.dev_bot_user_id = dev_bot_user_id
        self.pm_bot_token = pm_bot_token
        self.pm_bot_user_id = pm_bot_user_id
        self.bot_user_ids = {dev_bot_user_id, pm_bot_user_id} - {""}
        self._last_seen_ts: int = 0  # create_at timestamp of last seen post

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> tuple[bool, list[str]]:
        """Validate configuration and connectivity.

        Returns:
            Tuple of (success: bool, errors: list[str])
        """
        errors: list[str] = []

        # Check Mattermost channel exists and bot token works
        try:
            # Try to read from the channel
            _ = self.read_posts(limit=1)
            # If we got here, the channel exists and token works
            logger.info("Mattermost validation passed")
        except Exception as e:
            errors.append(f"Mattermost API failed: {e}")

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Send (dual identity)
    # ------------------------------------------------------------------

    def send(self, message: str, sender: str | None = None, root_id: str | None = None, channel_id: str | None = None) -> dict:
        """Send a message to the channel (optionally as a thread reply).

        Uses the Dev Agent bot by default, or PM Agent bot if sender is "PM Agent".
        """
        target_channel = channel_id or self.channel_id
        token = self.pm_bot_token if sender == "PM Agent" else self.dev_bot_token

        return self._send_via_api(message, token, root_id=root_id, channel_id=target_channel)

    def _send_via_api(self, message: str, bot_token: str, root_id: str | None = None, channel_id: str | None = None) -> dict:
        """Send via Mattermost API."""
        data = {
            "channel_id": channel_id or self.channel_id,
            "message": message,
        }
        if root_id:
            data["root_id"] = root_id

        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                f"{self.mattermost_url}/api/v4/posts",
                "-H", f"Authorization: Bearer {bot_token}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(data),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Failed to send message: {result.stderr}")
            return {"error": result.stderr}

        try:
            response = json.loads(result.stdout)
            if "id" in response:
                logger.info(f"Message sent successfully: {response['id']}")
            return response
        except json.JSONDecodeError:
            logger.error(f"Failed to parse response: {result.stdout}")
            return {"error": "Failed to parse response"}

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_posts(self, limit: int = 100) -> list[dict]:
        """Read recent posts from the channel."""
        if not self.dev_bot_token:
            logger.warning("No dev_bot_token configured, cannot read posts")
            return []

        result = subprocess.run(
            [
                "curl", "-s",
                f"{self.mattermost_url}/api/v4/channels/{self.channel_id}/posts?per_page={limit}",
                "-H", f"Authorization: Bearer {self.dev_bot_token}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Failed to read posts: {result.stderr}")
            return []

        try:
            data = json.loads(result.stdout)
            posts = data.get("posts", {})
            order = data.get("order", [])
            return [posts[post_id] for post_id in order if post_id in posts]
        except json.JSONDecodeError:
            logger.error(f"Failed to parse posts: {result.stdout}")
            return []

    def get_unprocessed_messages(self) -> list[dict]:
        """Get new messages since last check."""
        posts = self.read_posts(limit=100)

        # Filter to messages we haven't processed
        new_messages = []
        for post in posts:
            post_ts = post.get("create_at", 0)
            if post_ts > self._last_seen_ts and post.get("user_id") in self.bot_user_ids:
                continue  # Skip bot messages
            if post_ts > self._last_seen_ts:
                new_messages.append(post)

        if posts:
            self._last_seen_ts = max(p.get("create_at", 0) for p in posts)

        return new_messages

    def wait_for_reply(self, root_id: str, timeout: int = 120) -> dict | None:
        """Wait for a reply to a thread."""
        start = time.time()
        while time.time() - start < timeout:
            posts = self.read_posts(limit=100)
            for post in posts:
                if post.get("root_id") == root_id and post.get("user_id") not in self.bot_user_ids:
                    return post
            time.sleep(2)
        return None

    def wait_for_response(self, timeout: int = 300) -> str | None:
        """Wait for a human response in the channel (any message not from bots)."""
        start = time.time()
        while time.time() - start < timeout:
            posts = self.read_posts(limit=50)
            for post in posts:
                # Skip bot messages
                if post.get("user_id") in self.bot_user_ids:
                    continue
                # Skip system messages
                if post.get("type"):
                    continue
                # Skip messages we already processed
                if post.get("create_at", 0) <= self._last_seen_ts:
                    continue
                # Found a human message
                self._last_seen_ts = max(self._last_seen_ts, post.get("create_at", 0))
                return post.get("message", "")
            time.sleep(2)
        return None

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def get_channels(self) -> list[dict]:
        """Get all channels the bot is a member of."""
        # Use the Mattermost API to get channels for this user
        url = f"{self.mattermost_url}/api/v4/users/{self.dev_bot_user_id}/teams"
        curl_cmd = [
            "curl", "-sf", url,
            "-H", f"Authorization: Bearer {self.dev_bot_token}",
        ]
        try:
            output = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=30).stdout
            teams = json.loads(output)
        except Exception as e:
            logger.warning(f"Failed to get teams: {e}")
            return [{"id": self.channel_id, "name": "default"}]

        all_channels = []
        for team in teams:
            team_id = team.get("id")
            # Get channels for this team
            url = f"{self.mattermost_url}/api/v4/users/{self.dev_bot_user_id}/teams/{team_id}/channels"
            curl_cmd = [
                "curl", "-sf", url,
                "-H", f"Authorization: Bearer {self.dev_bot_token}",
            ]
            try:
                output = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=30).stdout
                channels = json.loads(output)
                all_channels.extend(channels)
            except Exception as e:
                logger.warning(f"Failed to get channels for team {team_id}: {e}")

        if not all_channels:
            all_channels = [{"id": self.channel_id, "name": "default"}]

        logger.info(f"Found {len(all_channels)} channels")
        return all_channels

    def read_posts_from_channel(self, channel_id: str, limit: int = 100, after: int = 0) -> list[dict]:
        """Read recent posts from a specific channel."""
        if not self.dev_bot_token:
            logger.warning("No dev_bot_token configured, cannot read posts")
            return []

        # Note: Mattermost's "after" param expects a post ID, not timestamp
        # For simplicity, we just read the latest posts and filter client-side
        url = f"{self.mattermost_url}/api/v4/channels/{channel_id}/posts?per_page={limit}"

        result = subprocess.run(
            [
                "curl", "-s", url,
                "-H", f"Authorization: Bearer {self.dev_bot_token}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Failed to read posts: {result.stderr}")
            return []

        try:
            data = json.loads(result.stdout)
            posts = data.get("posts", {})
            order = data.get("order", [])
            all_posts = [posts[post_id] for post_id in order if post_id in posts]

            # Filter by timestamp if after is provided (workaround for post ID issue)
            if after > 0:
                all_posts = [p for p in all_posts if p.get("create_at", 0) > after]

            return all_posts
        except json.JSONDecodeError:
            logger.error(f"Failed to parse posts: {result.stdout}")
            return []

    def read_new_human_messages(self, channel_id: str = None) -> list[dict]:
        """Read new human messages (not bot messages) from the channel since last check."""
        ch_id = channel_id or self.channel_id
        if not self.dev_bot_token:
            logger.warning("No dev_bot_token configured, cannot read messages")
            return []

        # Read posts from channel
        posts = self.read_posts_from_channel(ch_id, limit=20)

        # Filter to only human messages (not from bots)
        human_posts = []
        for post in posts:
            user_id = post.get("user_id")
            # Skip bot messages
            if user_id in self.bot_user_ids:
                continue
            # Skip system messages
            if post.get("type"):
                continue
            # Skip if we already processed this (based on timestamp)
            post_ts = post.get("create_at", 0)
            if post_ts <= self._last_seen_ts:
                continue
            human_posts.append(post)

        # Update last seen timestamp
        if posts:
            self._last_seen_ts = max(self._last_seen_ts, max(p.get("create_at", 0) for p in posts))

        return human_posts

    def mark_current_position(self) -> None:
        """Mark the current position in the channel by reading the latest post."""
        # This is used to track where we are in the conversation
        # Just read the latest posts to update _last_seen_ts
        posts = self.read_posts(limit=5)
        if posts:
            self._last_seen_ts = max(self._last_seen_ts, max(p.get("create_at", 0) for p in posts))

