#!/usr/bin/env python3
"""
Responder service - Listens for /suggest and @mentions, kicks off workflows.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import anthropic
import redis
import yaml

from mattermost_bridge import MattermostBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("responder.log"),
    ],
)
logger = logging.getLogger("responder")


class Responder:
    """Listens for commands and @mentions, spawns orchestrator workflows."""

    def __init__(self, config: dict):
        self.cfg = config

        # Extract Mattermost config
        mattermost = config.get("mattermost", {})
        openclaw = config.get("openclaw", {})

        self.bridge = MattermostBridge(
            ssh_host=openclaw.get("ssh_host", "sb@mac-mini-i7.local"),
            channel_id=mattermost.get("channel_id", ""),
            mattermost_url=mattermost.get("url", "http://localhost:8065"),
            dev_bot_token=mattermost.get("dev_bot_token", ""),
            dev_bot_user_id=mattermost.get("dev_bot_user_id", ""),
            pm_bot_token=mattermost.get("pm_bot_token", ""),
            pm_bot_user_id=mattermost.get("pm_bot_user_id", ""),
            openclaw_account=openclaw.get("openclaw_account"),
            use_ssh=False,  # Run locally since we're on the same host
        )

        self.last_check = int(time.time() * 1000)  # milliseconds
        self.orchestrator_process: Optional[subprocess.Popen] = None
        self.processed_messages: set[str] = set()  # Track processed message IDs

        # Store minimax API config for responding to PM questions
        self.minimax_api_key = openclaw.get("anthropic_api_key", "")
        self.minimax_base_url = openclaw.get("anthropic_base_url", "https://api.minimax.io/anthropic")
        self.minimax_model = openclaw.get("anthropic_model", "MiniMax-M2.1")

        # Initialize Redis client
        redis_config = config.get("redis_streams", {})
        self.redis_url = redis_config.get("url", "redis://localhost:6379")
        self.redis_stream = redis_config.get("stream", "feature-requests")
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to subprocess mode.")
            self.redis = None

    def run(self) -> None:
        """Main loop - poll for commands."""
        logger.info("Responder started, listening for commands...")

        # Validate config on startup
        self.bridge.validate()

        # Get all channels the bot is in
        logger.info("Fetching channels...")
        self.channels = self.bridge.get_channels()
        self.channel_last_seen: dict[str, int] = {}

        while True:
            try:
                self._check_for_commands()
                # Periodically clean up old message IDs to prevent memory growth
                if len(self.processed_messages) > 1000:
                    # Keep only the most recent 500
                    self.processed_messages = set(list(self.processed_messages)[-500:])
            except Exception:
                logger.exception("Error checking for commands")

            time.sleep(5)  # Poll every 5 seconds

    def _check_for_commands(self) -> None:
        """Check all channels for new messages with commands or @mentions."""
        for channel in self.channels:
            channel_id = channel.get("id")
            if not channel_id:
                continue

            # Get last seen timestamp for this channel
            last_seen = self.channel_last_seen.get(channel_id, 0)

            # Read posts from this channel
            try:
                posts = self.bridge.read_posts_from_channel(channel_id, limit=20, after=last_seen)
            except Exception as e:
                logger.warning(f"Failed to read posts from {channel_id}: {e}")
                continue

            for p in posts:
                # Skip if already processed this message ID
                msg_id = p.get("id")
                if msg_id in self.processed_messages:
                    continue
                # Mark as processed immediately
                self.processed_messages.add(msg_id)

                # Skip bot messages
                if p.get("user_id") in self.bridge.bot_user_ids:
                    continue
                # Skip system messages
                if p.get("type"):
                    continue

                text = p.get("message", "").strip()

                # Check if this is a question (ends with ? or contains question words)
                # This should be handled before /suggest check
                is_question = text.strip().endswith("?")
                question_phrases = ["can you", "could you", "would you", "will you", "how do", "how can", "what is", "what's", "why is", "why does", "when will", "should i", "should we"]
                # Check if any question phrase is in the text (after any @mention)
                text_lower = text.lower()
                is_question = is_question or any(phrase in text_lower for phrase in question_phrases)

                # Check for /resume command
                if "/resume" in text.lower():
                    self._handle_resume(text, channel_id)
                    continue

                # Check for /suggest command (anywhere in message, but not questions)
                if "/suggest" in text.lower() and not is_question:
                    self._handle_suggest(text, channel_id)
                    continue

                # Check for @product-manager or @dev-agent mention
                if "@product-manager" in text.lower() or "@dev-agent" in text.lower():
                    self._handle_mention(text, channel_id, is_question=is_question)

            # Update last seen
            if posts:
                max_ts = max((p.get("create_at", 0) for p in posts), default=0)
                if max_ts > last_seen:
                    self.channel_last_seen[channel_id] = max_ts

    def _handle_suggest(self, text: str, channel_id: str) -> None:
        """Handle /suggest command - start orchestrator workflow."""
        # Extract feature name: /suggest "Add track pages" OR /suggest Add Redis Streams
        feature = None

        # Try quoted first: /suggest "Add track pages"
        if '"' in text:
            parts = text.split('"')
            if len(parts) >= 2:
                feature = parts[1]
        else:
            # Try text after /suggest: /suggest Add Redis Streams
            lower = text.lower()
            if "/suggest" in lower:
                idx = lower.index("/suggest") + len("/suggest")
                remainder = text[idx:].strip()
                if remainder:
                    feature = remainder

        logger.info(f"/suggest command received: feature={feature}")

        # Post acknowledgment
        # Publish feature request to Redis stream (or fallback to subprocess)
        self._publish_feature_request(feature=feature, channel_id=channel_id)

    def _handle_resume(self, text: str, channel_id: str) -> None:
        """Handle /resume command - resume workflow with auto-approve."""
        logger.info(f"/resume command received in channel {channel_id}")

        # Post acknowledgment
        self.bridge.send(
            "Resuming workflow with auto-approve...",
            sender="Responder",
            channel_id=channel_id,
        )

        # Publish resume request to Redis stream
        self._publish_feature_request(channel_id=channel_id, resume=True)

    def _handle_mention(self, text: str, channel_id: str, is_question: bool = False) -> None:
        """Handle @product-manager or @dev-agent mention."""
        logger.info(f"@mention in channel {channel_id}: {text[:100]}... is_question={is_question}")

        # Determine if it's PM or Dev (check in order - first match wins for precedence)
        text_lower = text.lower()
        is_pm = "@product-manager" in text_lower
        is_dev = "@dev-agent" in text_lower

        # Route to appropriate agent
        if is_dev:
            # @dev-agent mention - route to Dev Agent
            logger.info("Routing @dev-agent mention to Dev Agent")
            if is_question:
                logger.info("Detected question, answering directly")
                response = self._generate_response(text, channel_id, is_pm=False)
                self.bridge.send(response, sender="Dev Agent", channel_id=channel_id)
                return
            # Not a question - publish feature request to Redis stream
            self._publish_feature_request(channel_id=channel_id)
            return

        if not is_pm:
            # No recognized mention - shouldn't happen but handle gracefully
            logger.warning(f"No recognized agent mention in: {text[:50]}...")
            return

        # @product-manager mention - route to PM Agent
        logger.info("Routing @product-manager mention to PM Agent")
        if is_question:
            logger.info("Detected question, answering directly")
            response = self._generate_response(text, channel_id, is_pm=True)
            self.bridge.send(response, sender="PM Agent", channel_id=channel_id)
            return

        # Not a question - publish feature request to Redis stream
        self._publish_feature_request(channel_id=channel_id)

    def _get_project_for_channel(self, channel_id: str) -> tuple[str, str] | None:
        """Get project path and PRD path for a channel."""
        projects = self.cfg.get("projects", {})
        for proj_name, proj in projects.items():
            if proj.get("channel_id") == channel_id:
                return proj.get("path", ""), proj.get("prd_path", "docs/PRD.md")
        return None

    def _read_prd(self, project_path: str, prd_path: str, channel_id: str | None = None) -> str:
        """Read PRD file content, using Redis cache if available."""
        # Create cache key from project + prd path
        cache_key = f"prd:{project_path}:{prd_path}"

        # Try Redis cache first
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(f"PRD cache hit: {cache_key}")
                    return cached[:10000]
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # Read from file
        try:
            prd_full_path = Path(project_path) / prd_path
            content = prd_full_path.read_text()[:10000]  # Limit to 10k chars

            # Cache in Redis (expire after 1 hour)
            if self.redis and content:
                try:
                    self.redis.setex(cache_key, 3600, content)
                    logger.debug(f"PRD cached: {cache_key}")
                except Exception as e:
                    logger.warning(f"Redis set failed: {e}")

            return content
        except Exception as e:
            logger.warning(f"Failed to read PRD: {e}")
            return ""

    def _generate_response(self, message: str, channel_id: str, is_pm: bool) -> str:
        """Generate a response by routing to OpenClaw."""
        # Get project for this channel
        project_info = self._get_project_for_channel(channel_id)

        # Build prompt with context
        prompt = ""

        # For PM questions, inject PRD context
        if is_pm and project_info:
            project_path, prd_path = project_info
            prd_content = self._read_prd(project_path, prd_path)
            if prd_content:
                prompt += f"""You are a Product Manager. Use the following PRD context to answer questions.\n\n## PRD (relevant sections)\n{prd_content}\n\n---\n\n"""

        # Add channel context (recent messages)
        try:
            recent = self.bridge.read_posts_from_channel(channel_id, limit=5)
            if recent:
                prompt += "Recent conversation:\n"
                for msg in recent:
                    user = msg.get("user_id", "unknown")
                    text = msg.get("message", "")[:300]
                    prompt += f"- {user}: {text}\n"
                prompt += "\n"
        except Exception as e:
            logger.warning(f"Failed to get channel context: {e}")

        # Add the user's question
        prompt += f"User question: {message}\n\nRespond directly as the Product Manager would. Keep it friendly and concise."

        # Send to OpenClaw via SSH
        return self._send_to_openclaw(prompt)

    def _send_to_openclaw(self, prompt: str) -> str:
        """Send prompt to Claude via Minimax API."""
        if not self.minimax_api_key:
            logger.error("No minimax API key configured")
            return "Sorry, I'm not configured to answer questions."

        try:
            client = anthropic.Anthropic(
                api_key=self.minimax_api_key,
                base_url=self.minimax_base_url,
            )

            message = client.messages.create(
                model=self.minimax_model,
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Extract text from response
            response_text = ""
            for block in message.content:
                if hasattr(block, 'text'):
                    response_text += block.text

            logger.info("Minimax API response: %s", response_text[:100])
            return response_text[:1000]

        except Exception as e:
            logger.error("Minimax API failed: %s", e)
            return "Sorry, I couldn't get a response."

    def _spawn_orchestrator(self, feature: Optional[str] = None, channel_id: Optional[str] = None, resume: bool = False) -> None:
        """Spawn the orchestrator locally with uv (fallback when Redis unavailable)."""
        # Get project for this channel
        project_name = None
        if channel_id:
            projects = self.cfg.get("projects", {})
            for proj_name, proj in projects.items():
                if proj.get("channel_id") == channel_id:
                    project_name = proj_name
                    break

        # Build uv command
        cmd = ["uv", "run", "python", "orchestrator.py"]
        if project_name:
            cmd.extend(["--project", project_name])
        if feature:
            cmd.extend(["--feature", feature])
        if channel_id:
            cmd.extend(["--channel", channel_id])
        if resume:
            cmd.extend(["--resume", "--approve"])

        logger.info(f"Spawning orchestrator (fallback mode): {' '.join(cmd)}")

        # Run locally with uv in background, don't wait
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info(f"Orchestrator spawned with PID: {proc.pid}")
        except Exception as e:
            logger.error(f"Failed to spawn orchestrator: {e}")

    def _publish_feature_request(self, feature: Optional[str] = None, channel_id: Optional[str] = None, resume: bool = False) -> None:
        """Publish feature request to Redis stream for worker processing."""
        if not self.redis:
            logger.warning("Redis not available, falling back to subprocess")
            self._spawn_orchestrator(feature=feature, channel_id=channel_id, resume=resume)
            return

        # Get project for this channel
        project_name = None
        if channel_id:
            projects = self.cfg.get("projects", {})
            for proj_name, proj in projects.items():
                if proj.get("channel_id") == channel_id:
                    project_name = proj_name
                    break

        # Build the request payload
        payload = {
            "project_name": project_name or "",
            "channel_id": channel_id or "",
            "feature": feature or "",
            "command": "resume" if resume else "suggest",
        }

        try:
            # Add to Redis stream
            stream_name = self.redis_stream
            self.redis.xadd(stream_name, payload)
            logger.info(f"Published feature request to stream: {payload}")
        except Exception as e:
            logger.error(f"Failed to publish to Redis stream: {e}, falling back to subprocess")
            self._spawn_orchestrator(feature=feature, channel_id=channel_id, resume=resume)


def main():
    # Load config
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Allow local overrides
    local_path = Path(config_path).with_suffix(".local.yaml")
    if local_path.exists():
        with open(local_path) as f:
            local_cfg = yaml.safe_load(f) or {}
        # Deep merge local config into base config
        _deep_merge(config, local_cfg)

    responder = Responder(config)
    responder.run()


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override dict into base dict in-place."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


if __name__ == "__main__":
    main()
