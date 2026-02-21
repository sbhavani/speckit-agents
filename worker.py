#!/usr/bin/env python3
"""Worker that consumes feature requests from Redis stream and runs orchestrator.

Usage:
    python worker.py                     # Run with config.yaml
    python worker.py --config my.yaml    # Custom config
    python worker.py --dry-run           # Print actions without executing
    python worker.py --consumer worker1  # Named consumer (default: hostname)
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import redis
import yaml
from utils import deep_merge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("worker.log"),
    ],
)
logger = logging.getLogger("worker")


def load_config(path: str) -> dict:
    """Load configuration from YAML file."""
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Allow local overrides
    local = Path(path).with_suffix(".local.yaml")
    if local.exists():
        with open(local) as f:
            local_cfg = yaml.safe_load(f) or {}
        deep_merge(cfg, local_cfg)
    return cfg


class Worker:
    """Consumes feature requests from Redis stream and runs orchestrator."""

    def __init__(self, config: dict, consumer_name: str, dry_run: bool = False):
        self.cfg = config
        self.consumer_name = consumer_name
        self.dry_run = dry_run

        # Get Redis config
        redis_config = config.get("redis_streams", {})
        self.redis_url = redis_config.get("url", "redis://localhost:6379")
        self.stream_name = redis_config.get("stream", "feature-requests")
        self.consumer_group = redis_config.get("consumer_group", "orchestrator-workers")

        defaults = redis_config.get("defaults", {})
        self.block_ms = defaults.get("block_ms", 5000)
        self.count = defaults.get("count", 10)

        # Initialize Redis
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}")

        # Ensure consumer group exists
        self._ensure_consumer_group()

    def _ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            # First check if stream exists
            if self.redis.exists(self.stream_name):
                # Stream exists, create group
                self.redis.xgroup_create(
                    self.stream_name,
                    self.consumer_group,
                    id="0",
                    mkstream=False,
                )
                logger.info(f"Created consumer group: {self.consumer_group}")
            else:
                # Stream doesn't exist yet, create with mkstream
                self.redis.xgroup_create(
                    self.stream_name,
                    self.consumer_group,
                    id="0",
                    mkstream=True,
                )
                logger.info(f"Created stream and consumer group: {self.consumer_group}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"Consumer group already exists: {self.consumer_group}")
            elif "NOSPC" in str(e):
                logger.warning("Stream full, trimming old messages")
                self.redis.xtrim(self.stream_name, 1000, limit=100)
                self._ensure_consumer_group()  # Retry
            else:
                raise

    def run(self) -> None:
        """Main loop - consume messages from stream."""
        logger.info(f"Worker {self.consumer_name} starting, listening on stream: {self.stream_name}")

        while True:
            try:
                self._consume_messages()
            except redis.ResponseError as e:
                if "NOGROUP" in str(e) or "NOSPC" in str(e):
                    # Recreate consumer group if needed
                    logger.warning(f"Stream error: {e}, recreating group")
                    self._ensure_consumer_group()
                else:
                    logger.exception("Error in consumer loop")
                    time.sleep(5)
            except Exception:
                logger.exception("Error in consumer loop")
                time.sleep(5)  # Back off on error

    def _consume_messages(self) -> None:
        """Read messages from stream and process them."""
        # Process ONE message at a time for better load balancing
        # Use count=1 so workers can grab messages individually
        messages = self.redis.xreadgroup(
            self.consumer_group,
            self.consumer_name,
            {self.stream_name: ">"},
            count=1,  # One at a time for fair distribution
            block=100,
        )

        if not messages:
            # Try reading pending messages (for failed deliveries)
            messages = self.redis.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                {self.stream_name: "0"},  # Read pending
                count=1,
                block=100,
            )

        if not messages:
            return

        # Process each message
        # xreadgroup returns: [[stream_name, [[msg_id, {field: value}], ...]], ...]
        for stream_data in messages:
            stream_name = stream_data[0]
            entries = stream_data[1]

            stream_name = stream_name.decode() if isinstance(stream_name, bytes) else stream_name

            for msg_entry in entries:
                msg_id = msg_entry[0]
                data = msg_entry[1]
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                self._process_message(msg_id_str, data)

    def _process_message(self, msg_id: str, data: dict) -> None:
        """Process a single feature request message."""
        # Skip stale messages (older than 60 seconds) to prevent duplicate workflows
        try:
            msg_time = int(msg_id.split('-')[0])
            import time
            if time.time() * 1000 - msg_time > 60000:
                logger.info(f"Skipping stale message {msg_id}")
                self.redis.xack(self.stream_name, self.consumer_group, msg_id)
                return
        except (ValueError, IndexError):
            pass  # Process normally if we can't parse the timestamp

        # Decode bytes if needed
        if isinstance(data, dict):
            payload = {k.decode() if isinstance(k, bytes) else k:
                       v.decode() if isinstance(v, bytes) else v
                       for k, v in data.items()}
        else:
            payload = data

        # Skip duplicate messages only when feature is specified (not for /suggest)
        # This allows multiple /suggest commands but dedups --feature requests
        import hashlib, json
        feature = payload.get('feature', '')
        if feature:
            dedup_key = f"{payload.get('project', '')}:{payload.get('command', '')}:{feature}"
            msg_hash = hashlib.sha256(dedup_key.encode()).hexdigest()[:16]
            processed_key = f"processed:{msg_hash}"

            if self.redis.setnx(processed_key, "1"):
                self.redis.expire(processed_key, 3600)  # Expire after 1 hour
            else:
                logger.info(f"Skipping duplicate message {msg_id} (hash: {msg_hash})")
                self.redis.xack(self.stream_name, self.consumer_group, msg_id)
                return

        logger.info(f"Received message {msg_id}: {payload}")

        # Support both "project" (orchestrator) and "project_name" (legacy)
        project_name = payload.get("project") or payload.get("project_name", "")
        channel_id = payload.get("channel_id", "")
        feature = payload.get("feature", "")
        command = payload.get("command", "suggest")
        use_simple = payload.get("simple", False)  # Optional: run with --simple flag

        if self.dry_run:
            logger.info("[DRY RUN] Would run orchestrator with:")
            logger.info(f"  project: {project_name}")
            logger.info(f"  channel: {channel_id}")
            logger.info(f"  feature: {feature}")
            logger.info(f"  command: {command}")
            # Ack the message anyway
            self.redis.xack(self.stream_name, self.consumer_group, msg_id)
            return

        try:
            # Build the orchestrator command
            # Default: --feature runs full dev cycle (DEV_SPECIFY → DEV_PLAN → DEV_TASKS → PLAN_REVIEW → DEV_IMPLEMENT → CREATE_PR)
            # With --simple: skips specify/plan/tasks, goes straight to implement
            cmd = ["uv", "run", "python", "orchestrator.py"]
            if use_simple:
                cmd.append("--simple")
            if project_name:
                cmd.extend(["--project", project_name])
            if channel_id:
                cmd.extend(["--channel", channel_id])
            if feature:
                # Use = syntax to avoid issues with features starting with --
                cmd.extend([f"--feature={feature}"])
            if payload.get("tools") == "enabled":
                cmd.append("--tools")
            if command == "resume":
                cmd.extend(["--resume", "--approve"])


            logger.info(f"Running orchestrator: {' '.join(cmd)}")

            # Clear CLAUDECODE env var so orchestrator can spawn claude -p
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            logger.info(f"CLAUDECODE in subprocess env: {'CLAUDECODE' in env}")

            # Run the orchestrator and wait for completion
            # Use DEVNULL to avoid TTY issues when run in background
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                timeout=7200,  # 2 hour timeout
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if result.returncode == 0:
                logger.info("Orchestrator completed successfully")
                # Ack the message on success
                self.redis.xack(self.stream_name, self.consumer_group, msg_id)
            else:
                logger.error(f"Orchestrator failed with code {result.returncode}")
                # Don't ack - could retry or move to dead letter
                # For now, ack anyway to avoid stuck messages
                self.redis.xack(self.stream_name, self.consumer_group, msg_id)

        except subprocess.TimeoutExpired:
            logger.error("Orchestrator timed out after 2 hours")
            self.redis.xack(self.stream_name, self.consumer_group, msg_id)
        except Exception as e:
            logger.exception(f"Error running orchestrator: {e}")
            # Don't ack - could retry
            self.redis.xack(self.stream_name, self.consumer_group, msg_id)


def main():
    parser = argparse.ArgumentParser(description="Worker that consumes feature requests from Redis stream")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--consumer", type=str, default=None, help="Consumer name (default: hostname)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    args = parser.parse_args()

    config_path = args.config
    if not os.path.exists(config_path):
        # Try relative to script directory
        config_path = os.path.join(os.path.dirname(__file__), args.config)

    config = load_config(config_path)

    # Use hostname as default consumer name
    consumer_name = args.consumer or f"worker-{os.uname().nodename}"

    worker = Worker(config, consumer_name, dry_run=args.dry_run)
    worker.run()


if __name__ == "__main__":
    main()
