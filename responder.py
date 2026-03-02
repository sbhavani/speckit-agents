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
from utils import deep_merge

# Check for LOG_LEVEL env var
log_level = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level.upper(), logging.INFO),
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
        llm_config = config.get("llm", {})

        self.bridge = MattermostBridge(
            channel_id=mattermost.get("channel_id", ""),
            mattermost_url=mattermost.get("url", "http://localhost:8065"),
            dev_bot_token=mattermost.get("dev_bot_token", ""),
            dev_bot_user_id=mattermost.get("dev_bot_user_id", ""),
            pm_bot_token=mattermost.get("pm_bot_token", ""),
            pm_bot_user_id=mattermost.get("pm_bot_user_id", ""),
        )

        self.last_check = int(time.time() * 1000)  # milliseconds
        self.processed_messages: set[str] = set()  # Track processed message IDs

        # Store LLM API config for responding to PM questions
        self.minimax_api_key = config.get("openclaw", {}).get("anthropic_api_key", "") or llm_config.get("api_key", "")
        self.minimax_base_url = llm_config.get("base_url", "https://api.minimax.io/anthropic")
        self.minimax_model = llm_config.get("model", "MiniMax-M2.1")

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
        logger.debug(f"Checking {len(self.channels)} channels for commands...")
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

                # Skip bot messages (by user_id if configured, or by content patterns)
                if p.get("user_id") in self.bridge.bot_user_ids:
                    logger.debug(f"Skipping bot message: {p.get('user_id')}")
                    continue

                # Also skip messages that look like bot messages (Feature Suggestion, etc.)
                text = p.get("message", "")
                bot_patterns = ["Feature Suggestion", "**Feature Suggestion**", "📋", "📐", "📝", "PM Agent", "Orchestrator", "Product Manager"]
                if any(pattern in text for pattern in bot_patterns):
                    logger.debug(f"Skipping bot message (content): {text[:50]}")
                    continue

                # Skip system messages
                if p.get("type"):
                    logger.debug(f"Skipping system message: {p.get('type')}")
                    continue

                logger.info(f"Found message: {p.get('message', '')[:50]}")

                text = p.get("message", "").strip()
                logger.debug(f"Processing message: {text[:50]}, lower: {text.lower()[:50]}")

                # Check if this is a question (ends with ? or contains question words)
                # This should be handled before /suggest check
                is_question = text.strip().endswith("?")
                question_phrases = ["can you", "could you", "would you", "will you", "how do", "how can", "what is", "what's", "why is", "why does", "when will", "should i", "should we"]
                # Check if any question phrase is in the text (after any @mention)
                text_lower = text.lower()
                is_question = is_question or any(phrase in text_lower for phrase in question_phrases)

                # Check for @product-manager approve/reject commands
                # Require @product-manager prefix to avoid accidental triggers
                if "@product-manager" in text.lower():
                    if "approve" in text.lower() or "yes" in text.lower():
                        root_id = p.get("root_id", "")
                        self._handle_approve(channel_id, root_id=root_id)
                        continue
                    if "reject" in text.lower() or "no" in text.lower():
                        self._handle_reject(channel_id)
                        continue

                # Check for /resume command
                if "/resume" in text.lower():
                    self._handle_resume(text, channel_id)
                    continue

                # Check for /speckit.suggest command (anywhere in message, but not questions)
                has_suggest = "/speckit.suggest" in text.lower() or "/suggest" in text.lower()
                logger.info(f"Check /suggest: has_suggest={has_suggest}, is_question={is_question}, text={text[:30]}")
                if has_suggest:
                    logger.info(f"Found /suggest: is_question={is_question}, text={text[:30]}")
                    if not is_question:
                        logger.info(f"Detected /suggest command in: {text[:50]}")
                        try:
                            self._handle_suggest(text, channel_id)
                        except Exception as e:
                            logger.exception(f"Error handling suggest: {e}")
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

    def _handle_approve(self, channel_id: str, root_id: str = "") -> None:
        """Handle approval - run orchestrator with --resume --approve."""
        logger.info(f"Approval detected in channel {channel_id}, root_id={root_id}")

        # Try to find the PM's suggestion from Redis using the thread root_id
        feature = self._find_pm_suggestion(channel_id, thread_id=root_id)
        if feature:
            logger.info(f"Found PM suggestion in Redis: {feature.get('feature', '')[:50]}...")
        else:
            logger.warning("No PM suggestion found in Redis, will try channel messages")
            # Fallback: look in channel messages
            feature_text = self._find_pm_suggestion_from_channel(channel_id)
            if feature_text:
                feature = {"feature": feature_text}
                logger.info(f"Found PM suggestion from channel: {feature_text[:50]}...")

        # Publish to Redis with resume + approve flags and the feature
        self._publish_feature_request(
            channel_id=channel_id,
            resume=True,
            approve=True,
            feature=feature.get("feature") if isinstance(feature, dict) else feature,
        )

    def _find_pm_suggestion(self, channel_id: str, thread_id: str = None) -> dict | None:
        """Find the PM's suggestion from Redis."""
        if not self.redis:
            return None

        try:
            import json

            # First try to find by the specific thread_id if provided
            if thread_id:
                key = f"agent-team:pm-suggestion:{channel_id}:{thread_id}"
                data = self.redis.get(key)
                if data:
                    result = json.loads(data)
                    # Verify this is a real suggestion, not just "/suggest"
                    if result.get("feature") and result.get("feature") != "/suggest":
                        return result

            # If no thread_id or not found, scan for keys and find the most recent one
            # that has a valid suggestion (not empty or "/suggest")
            latest_key = None
            latest_time = 0
            for key in self.redis.scan_iter(match=f"agent-team:pm-suggestion:{channel_id}:*"):
                data = self.redis.get(key)
                if data:
                    result = json.loads(data)
                    # Check if this is a valid suggestion
                    feature = result.get("feature", "")
                    if feature and feature != "/suggest" and not feature.startswith("@"):
                        # This looks like a real feature suggestion
                        # Use TTL to determine recency - shorter TTL = more recent
                        ttl = self.redis.ttl(key)
                        if ttl > latest_time:
                            latest_time = ttl
                            latest_key = result

            if latest_key:
                return latest_key

            return None
        except Exception as e:
            logger.warning(f"Error finding PM suggestion in Redis: {e}")
            return None

    def _find_pm_suggestion_from_channel(self, channel_id: str) -> str | None:
        """Fallback: Find the PM's suggestion from recent messages in the channel."""
        try:
            # Get recent messages from the channel
            posts = self.bridge.read_posts_from_channel(channel_id, limit=10)
            if not posts:
                return None

            # Look for PM Agent's message with "Feature Suggestion"
            # PM Agent is a bot, so we look for bot messages containing "Feature Suggestion"
            for post in posts:
                message = post.get("message", "")
                # PM Agent posts with "Feature Suggestion" - look for that
                if "Feature Suggestion" in message:
                    # Extract the feature name - it's in **bold** text after "Feature Suggestion"
                    import re
                    # Match **feature name** (priority) pattern
                    match = re.search(r'\*\*([^*]+)\*\*', message)
                    if match:
                        feature_name = match.group(1).strip()
                        # Make sure this is the feature name, not something else
                        # The format is "**FeatureName (Priority: P1)**"
                        if "priority" in message.lower():
                            return feature_name
                    # Also try to find lines that start with "feature:" or "Feature:"
                    feature_match = re.search(r'[Ff]eature:\s*([^\n]+)', message)
                    if feature_match:
                        return feature_match.group(1).strip()

            return None
        except Exception as e:
            logger.warning(f"Error finding PM suggestion: {e}")
            return None

    def _handle_reject(self, channel_id: str) -> None:
        """Handle rejection - do nothing or acknowledge."""
        logger.info(f"Rejection detected in channel {channel_id}")

        # Post acknowledgment
        self.bridge.send(
            "Feature rejected. Starting fresh workflow...",
            sender="Responder",
            channel_id=channel_id,
        )

    def _handle_mention(self, text: str, channel_id: str, is_question: bool = False) -> None:
        """Handle @product-manager or @dev-agent mention."""
        logger.info(f"@mention in channel {channel_id}: {text[:100]}... is_question={is_question}")

        # Determine if it's PM or Dev
        is_pm = "@product-manager" in text.lower()
        # @dev-agent not implemented yet - fall through to PM
        if not is_pm:
            self.bridge.send(
                "Use @product-manager for questions for now. @dev-agent coming soon!",
                sender="Responder",
                channel_id=channel_id,
            )
            return

        # If it's a question, just answer it directly (don't spawn orchestrator)
        if is_question:
            logger.info("Detected question, answering directly")
            response = self._generate_response(text, channel_id, is_pm)
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
        return self._send_to_llm(prompt)

    def _send_to_llm(self, prompt: str) -> str:
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

    def _publish_feature_request(self, feature: Optional[str] = None, channel_id: Optional[str] = None, resume: bool = False, approve: bool = False) -> None:
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
        if approve:
            payload["approve"] = "true"

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
        deep_merge(config, local_cfg)

    responder = Responder(config)
    responder.run()


if __name__ == "__main__":
    main()
