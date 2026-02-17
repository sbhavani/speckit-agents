"""Mattermost communication bridge with dual bot identities.

Sends messages via either:
- OpenClaw CLI (over SSH) for the Dev Agent (openclaw bot)
- Mattermost REST API (over SSH + curl) for the PM Agent (product-manager bot)

Reads messages via the Mattermost REST API, since OpenClaw's ``message read``
is not supported for the Mattermost channel plugin.
"""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


class MattermostBridge:
    """Send and receive Mattermost messages through a remote host.

    Supports two bot identities: a Dev bot (via OpenClaw) and a PM bot
    (via Mattermost API). Human messages are those from neither bot.
    """

    def __init__(
        self,
        ssh_host: str,
        channel_id: str,
        mattermost_url: str = "http://localhost:8065",
        dev_bot_token: str = "",
        dev_bot_user_id: str = "",
        pm_bot_token: str = "",
        pm_bot_user_id: str = "",
        openclaw_account: str | None = None,
    ):
        self.ssh_host = ssh_host
        self.channel_id = channel_id
        self.mattermost_url = mattermost_url
        self.dev_bot_token = dev_bot_token
        self.dev_bot_user_id = dev_bot_user_id
        self.pm_bot_token = pm_bot_token
        self.pm_bot_user_id = pm_bot_user_id
        self.openclaw_account = openclaw_account
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

        # 1. Check SSH connectivity
        try:
            result = self._ssh(["echo", "ok"], timeout=10)
            if "ok" not in result:
                errors.append("SSH connection test failed")
        except Exception as e:
            errors.append(f"SSH connection failed: {e}")
            return False, errors

        # 2. Check Mattermost channel exists and bot token works
        try:
            # Try to read from the channel
            posts = self.read_posts(limit=1)
            # If we got here, the channel exists and token works
            logger.info("Mattermost validation passed")
        except Exception as e:
            errors.append(f"Mattermost API failed: {e}")

        # 3. Check OpenClaw if configured (skip for localhost)
        # Note: OpenClaw validation is optional - it may not be reachable
        # if running locally or SSH isn't set up
        if self.openclaw_account and self.ssh_host != "localhost":
            try:
                result = self._ssh(
                    ["openclaw", "status"],
                    timeout=10,
                )
                logger.info("OpenClaw validation passed")
            except Exception as e:
                logger.warning("OpenClaw check failed (continuing anyway): %s", e)

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Send (dual identity)
    # ------------------------------------------------------------------

    def send(self, message: str, sender: str | None = None, root_id: str | None = None) -> dict:
        """Send a message to the channel (optionally as a thread reply).

        Priority:
        1. If sender is "PM Agent", posts via PM bot's Mattermost token
        2. If root_id is provided (threading), posts via API with dev_bot_token
        3. Otherwise posts via OpenClaw CLI (Dev bot / Orchestrator)

        Note: OpenClaw CLI doesn't support threading, so threads are sent via API.
        """
        # PM Agent always uses PM bot token
        if sender and sender == "PM Agent" and self.pm_bot_token:
            return self._send_via_api(message, self.pm_bot_token, root_id)
        # Threading requires API (OpenClaw doesn't support it)
        if root_id and self.dev_bot_token:
            return self._send_via_api(message, self.dev_bot_token, root_id)
        # Default: use OpenClaw CLI
        return self._send_via_openclaw(message, sender)

    def _send_via_openclaw(self, message: str, sender: str | None = None) -> dict:
        """Send via OpenClaw CLI (appears as the openclaw/dev bot)."""
        if sender:
            text = f"**[{sender}]** {message}"
        else:
            text = message

        args = [
            "openclaw", "message", "send",
            "--channel", "mattermost",
            "--target", f"channel:{self.channel_id}",
            "-m", self._shell_quote(text),
            "--json",
        ]
        if self.openclaw_account:
            args.extend(["--account", self.openclaw_account])

        output = self._ssh(args)
        logger.info("Sent (dev): %s", text[:100])
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"raw": output}

    def _send_via_api(self, message: str, bot_token: str, root_id: str | None = None) -> dict:
        """Send via Mattermost REST API (appears as the specified bot).

        If root_id is provided, posts as a reply to that post's thread.
        """
        payload = {"channel_id": self.channel_id, "message": message}
        if root_id:
            payload["root_id"] = root_id

        payload_json = json.dumps(payload)
        curl_cmd = [
            "curl", "-sf",
            "-X", "POST",
            f"'{self.mattermost_url}/api/v4/posts'",
            "-H", f"'Authorization: Bearer {bot_token}'",
            "-H", "'Content-Type: application/json'",
            "-d", self._shell_quote(payload_json),
        ]
        output = self._ssh(curl_cmd, timeout=15)
        logger.info("Sent (api%s): %s", f" thread:{root_id}" if root_id else "", message[:100])
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"raw": output}

    # ------------------------------------------------------------------
    # Read (via Mattermost REST API)
    # ------------------------------------------------------------------

    def read_posts(self, limit: int = 10, after: int = 0) -> list[dict]:
        """Read recent posts from the channel via the Mattermost API.

        Returns a list of post dicts sorted oldest-first, each containing:
        ``id``, ``message``, ``user_id``, ``create_at``, ``type``.
        """
        url = f"{self.mattermost_url}/api/v4/channels/{self.channel_id}/posts?per_page={limit}"
        if after:
            url += f"&since={after}"

        curl_cmd = [
            "curl", "-sf", f"'{url}'",
            "-H", f"'Authorization: Bearer {self.dev_bot_token}'",
        ]
        output = self._ssh(curl_cmd, timeout=15)

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("Could not parse Mattermost API response: %s", output[:200])
            return []

        posts = []
        for pid in data.get("order", []):
            p = data["posts"][pid]
            posts.append({
                "id": p["id"],
                "message": p.get("message", ""),
                "user_id": p.get("user_id", ""),
                "create_at": p.get("create_at", 0),
                "type": p.get("type", ""),
            })

        # Sort oldest first
        posts.sort(key=lambda x: x["create_at"])
        return posts

    def read_new_human_messages(self) -> list[dict]:
        """Read new non-bot, non-system messages since the last check."""
        posts = self.read_posts(limit=20, after=self._last_seen_ts)

        human = []
        for p in posts:
            # Skip system messages
            if p["type"]:
                continue
            # Skip all bot messages
            if p["user_id"] in self.bot_user_ids:
                continue
            # Skip posts we already saw
            if p["create_at"] <= self._last_seen_ts:
                continue
            human.append(p)

        if posts:
            self._last_seen_ts = max(p["create_at"] for p in posts)

        return human

    def mark_current_position(self) -> None:
        """Set the read cursor to now so wait_for_response only sees new messages."""
        posts = self.read_posts(limit=1)
        if posts:
            self._last_seen_ts = posts[-1]["create_at"]

    def wait_for_response(self, timeout: int = 300, poll_interval: int = 5) -> str | None:
        """Poll for a human response. Returns message text or None on timeout."""
        self.mark_current_position()

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_interval)
            new = self.read_new_human_messages()
            for msg in new:
                text = msg.get("message", "").strip()
                if text:
                    logger.info("Human response: %s", text[:100])
                    return text

        logger.info("Timed out waiting for response after %ds", timeout)
        return None

    # ------------------------------------------------------------------
    # SSH helper
    # ------------------------------------------------------------------

    def _ssh(self, remote_cmd: list[str], timeout: int = 30, max_retries: int = 3) -> str:
        """Run a command on the remote host via SSH with retry logic.

        Args:
            remote_cmd: Command to run on remote host
            timeout: Timeout for each attempt
            max_retries: Maximum number of retry attempts

        Raises:
            RuntimeError: If all retries fail
        """
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return self._ssh_once(remote_cmd, timeout)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    # Exponential backoff: 2s, 8s, 32s
                    backoff = 2 ** (attempt + 0)
                    logger.warning(
                        "SSH attempt %d/%d failed: %s. Retrying in %ds...",
                        attempt, max_retries, e, backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error("SSH failed after %d attempts: %s", max_retries, e)

        # All retries failed
        raise RuntimeError(f"SSH failed after {max_retries} attempts: {last_error}")

    def _ssh_once(self, remote_cmd: list[str], timeout: int = 30) -> str:
        """Run a single SSH command (no retry)."""
        # Add -o StrictHostKeyChecking=no to skip host key verification
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", self.ssh_host, " ".join(remote_cmd)]
        logger.debug("SSH: %s", " ".join(remote_cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Filter out the SSH banner
            lines = [l for l in stderr.splitlines() if not l.startswith("*") and "UNAUTHORIZED" not in l and "monitored" not in l and "Disconnect" not in l]
            clean_err = "\n".join(lines).strip()
            if clean_err:
                logger.error("SSH command error: %s", clean_err)
                raise RuntimeError(f"Remote command failed: {clean_err}")
        # Filter SSH banner from stdout too
        stdout = result.stdout
        lines = stdout.splitlines()
        filtered = []
        for line in lines:
            if line.startswith("***") or "UNAUTHORIZED" in line or "monitored" in line or "Disconnect" in line:
                continue
            filtered.append(line)
        return "\n".join(filtered).strip()

    @staticmethod
    def _shell_quote(s: str) -> str:
        """Quote a string for safe passing through SSH + shell."""
        escaped = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        return f"$'{escaped}'"
