"""Mattermost communication bridge via OpenClaw CLI over SSH."""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


class MattermostBridge:
    """Send and receive Mattermost messages through OpenClaw CLI on a remote host."""

    def __init__(self, ssh_host: str, channel_target: str, account: str | None = None):
        self.ssh_host = ssh_host
        self.channel_target = channel_target
        self.account = account
        self._last_message_id: str | None = None

    def _run_openclaw(self, args: list[str], timeout: int = 30) -> str:
        """Run an openclaw command on the remote host via SSH."""
        cmd = ["ssh", self.ssh_host, "openclaw " + " ".join(args)]
        logger.debug("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.error("openclaw error: %s", result.stderr)
            raise RuntimeError(f"openclaw command failed: {result.stderr}")
        return result.stdout.strip()

    def send(self, message: str, sender: str | None = None) -> None:
        """Send a message to the Mattermost channel."""
        if sender:
            text = f"**[{sender}]** {message}"
        else:
            text = message

        args = [
            "message", "send",
            "--channel", "mattermost",
            "--target", f"'{self.channel_target}'",
            "-m", self._shell_quote(text),
        ]
        if self.account:
            args.extend(["--account", self.account])

        self._run_openclaw(args)
        logger.info("Sent to %s: %s", self.channel_target, text[:100])

    def read_recent(self, limit: int = 10) -> list[dict]:
        """Read recent messages from the channel."""
        args = [
            "message", "read",
            "--channel", "mattermost",
            "--target", f"'{self.channel_target}'",
            "--limit", str(limit),
            "--json",
        ]
        if self.account:
            args.extend(["--account", self.account])

        output = self._run_openclaw(args, timeout=15)
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            logger.warning("Could not parse message read output: %s", output[:200])
            return []

    def read_new(self) -> list[dict]:
        """Read only messages newer than the last seen message."""
        args = [
            "message", "read",
            "--channel", "mattermost",
            "--target", f"'{self.channel_target}'",
            "--limit", "20",
            "--json",
        ]
        if self._last_message_id:
            args.extend(["--after", self._last_message_id])
        if self.account:
            args.extend(["--account", self.account])

        output = self._run_openclaw(args, timeout=15)
        try:
            messages = json.loads(output)
        except json.JSONDecodeError:
            return []

        if messages:
            self._last_message_id = messages[-1].get("id", self._last_message_id)
        return messages

    def wait_for_response(self, timeout: int = 300, poll_interval: int = 5) -> str | None:
        """Poll for a human response in the channel. Returns message text or None on timeout."""
        # Mark the current position so we only see new messages
        recent = self.read_recent(limit=1)
        if recent:
            self._last_message_id = recent[-1].get("id")

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_interval)
            new_messages = self.read_new()
            for msg in new_messages:
                # Skip bot messages (only care about human responses)
                is_bot = msg.get("isBot", False) or msg.get("bot", False)
                if not is_bot:
                    text = msg.get("text", msg.get("content", "")).strip()
                    if text:
                        logger.info("Human response: %s", text[:100])
                        return text
        logger.info("Timed out waiting for response after %ds", timeout)
        return None

    @staticmethod
    def _shell_quote(s: str) -> str:
        """Quote a string for safe passing through SSH + shell."""
        # Use $'...' syntax to handle special characters
        escaped = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        return f"$'{escaped}'"
