#!/usr/bin/env python3
"""Agent Team Orchestrator — PM + Developer agents collaborating via Mattermost.

Usage:
    python orchestrator.py                     # Run with config.yaml
    python orchestrator.py --config my.yaml    # Custom config
    python orchestrator.py --dry-run           # Skip Mattermost, print to stdout
    python orchestrator.py --loop              # Keep suggesting features after each PR
    python orchestrator.py --feature "desc"    # Skip PM, implement this feature directly
    python orchestrator.py --resume            # Resume from last saved state
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

import yaml

from mattermost_bridge import MattermostBridge
from state_redis import RedisState

logger = logging.getLogger(__name__)


# ANSI color codes
class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output."""
    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def _setup_logging() -> None:
    """Configure console (INFO) and file (DEBUG) logging handlers."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console handler — colored output
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(ColoredFormatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File handler — full timestamps, DEBUG level, append mode
    log_path = Path(__file__).resolve().parent / "orchestrator.log"
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)


_setup_logging()


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class Phase(Enum):
    INIT = auto()
    PM_SUGGEST = auto()
    REVIEW = auto()
    DEV_SPECIFY = auto()
    DEV_PLAN = auto()
    DEV_TASKS = auto()
    PLAN_REVIEW = auto()
    DEV_IMPLEMENT = auto()
    CREATE_PR = auto()
    PM_LEARN = auto()
    DONE = auto()


@dataclass
class WorkflowState:
    phase: Phase = Phase.INIT
    feature: dict = field(default_factory=dict)
    pm_session: str | None = None
    dev_session: str | None = None
    pr_url: str | None = None
    root_post_id: str | None = None  # For Mattermost thread


STATE_FILE = ".agent-team-state.json"

# Phase sequence: (Phase, method_name, is_checkpoint)
# Checkpoint phases return bool — False aborts the workflow.
PHASE_SEQUENCE_NORMAL: list[tuple[Phase, str, bool]] = [
    (Phase.INIT, "_phase_init", False),
    (Phase.PM_SUGGEST, "_phase_pm_suggest", False),
    (Phase.REVIEW, "_phase_review", True),
    (Phase.DEV_SPECIFY, "_phase_dev_specify", False),
    (Phase.DEV_PLAN, "_phase_dev_plan", False),
    (Phase.DEV_TASKS, "_phase_dev_tasks", False),
    (Phase.PLAN_REVIEW, "_phase_plan_review", True),
    (Phase.DEV_IMPLEMENT, "_phase_dev_implement", False),
    (Phase.CREATE_PR, "_phase_create_pr", False),
    (Phase.PM_LEARN, "_phase_pm_learn", False),
    (Phase.DONE, "_phase_done", False),
]

PHASE_SEQUENCE_FEATURE: list[tuple[Phase, str, bool]] = [
    (Phase.DEV_SPECIFY, "_phase_dev_specify", False),
    (Phase.DEV_PLAN, "_phase_dev_plan", False),
    (Phase.DEV_TASKS, "_phase_dev_tasks", False),
    (Phase.PLAN_REVIEW, "_phase_plan_review", True),
    (Phase.DEV_IMPLEMENT, "_phase_dev_implement", False),
    (Phase.CREATE_PR, "_phase_create_pr", False),
    (Phase.DONE, "_phase_done", False),
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    import yaml

    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Allow local overrides
    local = Path(path).with_suffix(".local.yaml")
    if local.exists():
        with open(local) as f:
            local_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, local_cfg)

    # Apply path mapping if HOST_WORKDIR is set
    host_workdir = os.environ.get("HOST_WORKDIR", "")
    if host_workdir and "projects" in cfg:
        # Map container paths to host paths
        path_map = cfg.get("host_path_map", {})
        for proj_name, proj in cfg["projects"].items():
            proj_path = proj.get("path", "")
            for container_prefix, host_prefix in path_map.items():
                if proj_path.startswith(container_prefix):
                    proj["path"] = proj_path.replace(container_prefix, host_prefix, 1)

    return cfg


def resolve_project_config(config: dict, project_name: str | None = None) -> tuple[str, str, str | None]:
    """Resolve project path, PRD path, and channel_id from config.

    Supports two formats:
    1. Single project: config["project"]["path"], config["project"]["prd_path"], config["project"]["channel_id"]
    2. Multi-project: config["projects"]["name"]["path"], config["projects"]["name"]["prd_path"], config["projects"]["name"]["channel_id"]

    Returns:
        tuple of (project_path, prd_path, channel_id)

    Raises:
        ValueError: If project not found or config is invalid
    """
    # Check for multi-project mode
    if "projects" in config:
        projects = config["projects"]
        if not projects:
            raise ValueError("No projects defined in config")

        # If no project specified, use the only one or error
        if not project_name:
            if len(projects) == 1:
                project_name = list(projects.keys())[0]
            else:
                raise ValueError(
                    f"Multiple projects defined: {list(projects.keys())}. "
                    "Use --project to specify which one."
                )

        if project_name not in projects:
            raise ValueError(f"Project '{project_name}' not found. Available: {list(projects.keys())}")

        proj = projects[project_name]
        return (
            proj["path"],
            proj.get("prd_path", "docs/PRD.md"),
            proj.get("channel_id"),
        )

    # Single project mode (legacy)
    if "project" not in config:
        raise ValueError("Config must have either 'project' or 'projects' key")

    proj = config["project"]
    return proj.get("path", "."), proj.get("prd_path", "docs/PRD.md"), proj.get("channel_id")

    return path


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Claude Code headless runner
# ---------------------------------------------------------------------------

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))


def run_claude(
    prompt: str,
    cwd: str,
    session_id: str | None = None,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
    timeout: int = 1800,
    max_retries: int = 2,
) -> dict:
    """Run `claude -p` and return parsed JSON output.

    Retries up to *max_retries* times on transient failures (non-zero exit,
    timeout) with exponential backoff (5s, 20s, …).

    Returns dict with keys: result, session_id, usage, etc.
    """
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if session_id:
        cmd += ["--resume", session_id]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    logger.info("Running claude -p (cwd=%s, session=%s)", cwd, session_id or "new")
    logger.debug("Prompt: %s", prompt[:200])

    # Clear CLAUDECODE env var so we can spawn from within a Claude Code session
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env
            )
        except subprocess.TimeoutExpired as e:
            logger.warning(
                "claude -p timed out after %ds (attempt %d/%d)",
                timeout, attempt, max_retries,
            )
            if attempt < max_retries:
                backoff = 5 * (4 ** (attempt - 1))
                logger.info("Retrying in %ds...", backoff)
                time.sleep(backoff)
                last_error = e
                continue
            # Final attempt — salvage what we can
            partial = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            try:
                parsed = json.loads(partial)
                return parsed
            except (json.JSONDecodeError, ValueError):
                return {"result": partial.strip(), "session_id": session_id, "_timeout": True}

        if result.returncode != 0:
            last_error = RuntimeError(f"claude -p failed: {result.stderr[:500]}")
            logger.error(
                "claude -p returned %d (attempt %d/%d): %s",
                result.returncode, attempt, max_retries, result.stderr[:200],
            )
            if attempt < max_retries:
                backoff = 5 * (4 ** (attempt - 1))
                logger.info("Retrying in %ds...", backoff)
                time.sleep(backoff)
                continue
            raise last_error

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Sometimes output is plain text even with --output-format json
            return {"result": result.stdout.strip(), "session_id": session_id}

    # Should not reach here, but satisfy type checker
    raise last_error  # type: ignore[misc]


def run_claude_stream(
    prompt: str,
    cwd: str,
    session_id: str | None = None,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
    timeout: int = 1800,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    """Run `claude -p` with stream-json output and optional progress callbacks.

    Args:
        prompt: The prompt to send to claude
        cwd: Working directory for the subprocess
        session_id: Optional session to resume
        allowed_tools: Optional list of allowed tools
        system_prompt: Optional system prompt
        timeout: Timeout in seconds
        progress_callback: Optional callback receiving parsed JSON events.
            Called for each line of stream-json output. Common events:
            - {"type": "tool_use", "name": "Read", "input": {...}}
            - {"type": "tool_result", "tool_use_id": "...", "content": "..."}
            - {"type": "message_delta", "usage": {...}}

    Returns:
        dict with keys: result, session_id, usage, etc.
    """
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session_id:
        cmd += ["--resume", session_id]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    logger.info("Running claude -p stream (cwd=%s, session=%s)", cwd, session_id or "new")
    logger.debug("Prompt: %s", prompt[:200])

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result_text = ""
    session_id_out = session_id
    timed_out = False

    try:
        logger.debug("Starting subprocess: %s", cmd)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
            bufsize=1,  # Line buffered
        )
        logger.debug("Subprocess started, pid=%s", proc.pid)

        # Read stdout line by line
        line_count = 0
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                line_count += 1
                line = line.strip()
                if not line:
                    continue
                logger.debug("Stream: Got line %d", line_count)
                try:
                    event = json.loads(line)
                    result_text += _extract_text_from_event(event)

                    # Track session_id from events
                    if event.get("type") == "session_id":
                        session_id_out = event.get("session_id")

                    # Call progress callback if provided
                    if progress_callback:
                        progress_callback(event)
                except json.JSONDecodeError:
                    # Skip non-JSON lines
                    continue
        except Exception as e:
            logger.debug("Error reading stdout: %s", e)

        # Wait for process with timeout
        start_time = time.time()
        while proc.poll() is None:
            if timeout and (time.time() - start_time) > timeout:
                proc.kill()
                timed_out = True
                logger.warning("claude -p stream timed out after %ds", timeout)
                break
            time.sleep(0.1)

    except Exception as e:
        logger.error("Error running claude stream: %s", e)

    if proc.returncode != 0 and proc.returncode is not None:
        stderr = proc.stderr.read() if proc.stderr else ""
        logger.error("claude -p stream failed: %s", stderr[:500])

    # If no result accumulated, fallback to regular mode
    if not result_text.strip():
        logger.warning("No output from stream, falling back to regular mode")
        return run_claude(
            prompt=prompt,
            cwd=cwd,
            session_id=session_id,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            timeout=timeout,
        )

    # Parse the accumulated result
    if result_text.strip().startswith("{"):
        try:
            parsed = json.loads(result_text.strip())
            if session_id_out:
                parsed["session_id"] = session_id_out
            if timed_out:
                parsed["_timeout"] = True
            return parsed
        except json.JSONDecodeError:
            pass

    result = {"result": result_text.strip(), "session_id": session_id_out}
    if timed_out:
        result["_timeout"] = True
    return result


def _extract_text_from_event(event: dict[str, Any]) -> str:
    """Extract text content from a stream-json event."""
    event_type = event.get("type", "")

    if event_type == "content_block_delta":
        # Text delta within a content block
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            return delta.get("text", "")
    elif event_type == "result":
        # Final result event contains the actual response
        return event.get("result", "")

    return ""


# ---------------------------------------------------------------------------
# Messenger — abstracts dry-run vs real Mattermost
# ---------------------------------------------------------------------------

class Messenger:
    """Unified interface for posting messages (Mattermost or stdout)."""

    def __init__(self, bridge: MattermostBridge | None, dry_run: bool = False):
        self.bridge = bridge
        self.dry_run = dry_run
        self._root_id: str | None = None  # Thread root post ID

    @property
    def root_id(self) -> str | None:
        return self._root_id

    def start_thread(self, message: str, sender: str = "Orchestrator") -> str | None:
        """Send a message and start a new thread. Returns the post ID."""
        if self.dry_run:
            print(f"\n--- [{sender}] ---\n{message}\n")
            return "dry-run-id"
        result = self.bridge.send(message, sender=sender, root_id=None)
        post_id = result.get("id")
        if post_id:
            self._root_id = post_id
            logger.info("Started thread: %s", post_id)
        return post_id

    def send(self, message: str, sender: str = "Orchestrator", root_id: str | None = None) -> None:
        """Send a message. If root_id not provided, uses stored thread root."""
        if self.dry_run:
            print(f"\n--- [{sender}] ---\n{message}\n")
        else:
            # Use provided root_id, or fall back to stored thread root
            effective_root = root_id or self._root_id
            self.bridge.send(message, sender=sender, root_id=effective_root)

    def wait_for_response(self, timeout: int = 300) -> str | None:
        if self.dry_run:
            try:
                return input("\n[Waiting for input — type response or press Enter to skip] > ").strip() or None
            except (EOFError, KeyboardInterrupt):
                return None
        return self.bridge.wait_for_response(timeout=timeout)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

PM_TOOLS = ["Read", "Glob", "Grep", "Bash(git log *)", "Bash(git diff *)", "Bash(git branch *)"]
DEV_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "Bash(git *)", "Bash(gh *)",
]


class Orchestrator:
    def __init__(
        self,
        config: dict,
        messenger: Messenger,
        project_path: str | None = None,
        prd_path: str | None = None,
    ):
        self.cfg = config
        self.msg = messenger
        # Original repo path from config
        self.original_path = project_path or config.get("project", {}).get("path", ".")
        # Worktree path (created on start)
        self.worktree_path: str | None = None
        # Current working path (original or worktree)
        self.project_path = self.original_path
        self.prd_path = prd_path or config.get("project", {}).get("prd_path", "docs/PRD.md")
        self.state = WorkflowState()
        self._workflow_type: str = "normal"  # "normal" or "feature"
        self._resuming: bool = False
        self._auto_approve: bool = False  # Skip plan review when resuming
        self._started_at: str | None = None
        self._phase_timings: list[tuple[str, float]] = []
        self._run_start_time: float | None = None

        # Optional Redis state storage
        redis_url = config.get("workflow", {}).get("redis_url")
        if redis_url:
            try:
                self._redis_state = RedisState(redis_url=redis_url)
                logger.info("Using Redis for state storage: %s", redis_url)
            except Exception as e:
                logger.warning("Failed to connect to Redis: %s, using file-based state", e)
                self._redis_state = None
        else:
            self._redis_state = None

    # -- State persistence -----------------------------------------------------

    def _state_file_path(self) -> Path:
        return Path(self.project_path) / STATE_FILE

    # -- Worktree management -----------------------------------------------------

    def _create_worktree(self) -> None:
        """Create a git worktree for the agent to work in."""
        if self.worktree_path:
            logger.info("Worktree already exists: %s", self.worktree_path)
            return

        # Check if original path is a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=self.original_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.info("Not a git repository, working in-place")
            return

        import tempfile

        # Extract project name from path
        project_name = Path(self.original_path).name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.worktree_path = str(Path(tempfile.gettempdir()) / f"agent-team-{project_name}-{timestamp}")

        logger.info("Creating worktree at: %s", self.worktree_path)

        # Create worktree from main branch
        result = subprocess.run(
            ["git", "worktree", "add", self.worktree_path, "main"],
            cwd=self.original_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try with -b flag if main doesn't exist or branch name conflicts
            branch_name = f"agent-worktree-{timestamp}"
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, self.worktree_path, "HEAD"],
                cwd=self.original_path,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create worktree: {result.stderr}")

        # Switch to worktree
        self.project_path = self.worktree_path
        logger.info("Worktree created successfully")

    def _cleanup_worktree(self) -> None:
        """Remove the worktree after workflow completes."""
        if not self.worktree_path:
            return

        logger.info("Cleaning up worktree: %s", self.worktree_path)

        try:
            # Remove the worktree (force if needed)
            subprocess.run(
                ["git", "worktree", "remove", "--force", self.worktree_path],
                cwd=self.original_path,
                capture_output=True,
                text=True,
            )
            logger.info("Worktree removed successfully")
        except Exception as e:
            logger.warning("Failed to remove worktree: %s", e)

        self.worktree_path = None
        self.project_path = self.original_path

    # ---------------------------------------------------------------------------

    def _save_state(self) -> None:
        """Serialize workflow state to JSON after each phase completes."""
        now = datetime.now(timezone.utc).isoformat()
        if self._started_at is None:
            self._started_at = now
        data = {
            "version": 1,
            "workflow_type": self._workflow_type,
            "phase": self.state.phase.name,
            "feature": self.state.feature,
            "pm_session": self.state.pm_session,
            "dev_session": self.state.dev_session,
            "pr_url": self.state.pr_url,
            "original_path": self.original_path,
            "worktree_path": self.worktree_path,
            "thread_root_id": self.msg.root_id,  # Save thread ID for resume
            "started_at": self._started_at,
            "updated_at": now,
        }

        # Save to Redis if available, otherwise use file
        if self._redis_state:
            self._redis_state.save(self.project_path, data)
            logger.info("State saved to Redis: phase=%s", self.state.phase.name)
        else:
            path = self._state_file_path()
            path.write_text(json.dumps(data, indent=2))
            logger.info("State saved to file: phase=%s", self.state.phase.name)

    def _load_state(self) -> dict | None:
        """Load state from Redis or file. Returns None if missing or corrupt."""
        # Try Redis first if available
        if self._redis_state:
            data = self._redis_state.load(self.project_path)
            if data:
                if data.get("version") != 1:
                    logger.warning("Unknown state version: %s", data.get("version"))
                    return None
                logger.info("State loaded from Redis: phase=%s", data.get("phase"))
                return data

        # Fall back to file
        path = self._state_file_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if data.get("version") != 1:
                logger.warning("Unknown state file version: %s", data.get("version"))
                return None
            logger.info("State loaded from file: phase=%s", data.get("phase"))
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load state file: %s", e)
            return None

    def _clear_state(self) -> None:
        """Delete state on successful completion."""
        # Clear Redis if available
        if self._redis_state:
            self._redis_state.delete(self.project_path)
            logger.info("State cleared from Redis")
        # Also clear file for clean state
        path = self._state_file_path()
        if path.exists():
            path.unlink()
            logger.info("State file cleared")

    # -- Run -------------------------------------------------------------------

    def run(self, loop: bool = False) -> None:
        """Execute the full workflow."""
        while True:
            try:
                self._run_once()
            except KeyboardInterrupt:
                self._save_state()
                self._post_summary(error="Interrupted by operator")
                break
            except Exception as e:
                self._save_state()
                logger.exception("Workflow error")
                self._post_summary(error=str(e))
                break

            if not loop:
                break
            # Reset state for next iteration
            self.state = WorkflowState()
            self._workflow_type = "normal"
            self._started_at = None
            self.msg.send("Starting next feature cycle...", sender="Orchestrator")

    def _run_once(self) -> None:
        """Execute the workflow using the phase sequence list."""
        self._phase_timings = []
        self._run_start_time = time.time()

        # Create worktree if not resuming (resuming uses existing worktree)
        if not self._resuming:
            self._create_worktree()

        sequence = (
            PHASE_SEQUENCE_FEATURE
            if self._workflow_type == "feature"
            else PHASE_SEQUENCE_NORMAL
        )

        # On resume, skip past the last completed phase
        start_idx = 0
        if self._resuming:
            for i, (phase, _, _) in enumerate(sequence):
                if phase == self.state.phase:
                    start_idx = i + 1
                    break
            self._resuming = False

        for phase, method_name, is_checkpoint in sequence[start_idx:]:
            method = getattr(self, method_name)
            t0 = time.time()
            if is_checkpoint:
                if not method():
                    self._phase_timings.append((phase.name, time.time() - t0))
                    return  # rejected
            else:
                method()
            self._phase_timings.append((phase.name, time.time() - t0))

            # Save after each phase; clear on DONE
            if phase == Phase.DONE:
                self._clear_state()
            else:
                self._save_state()

    # -- Phases ----------------------------------------------------------------

    def _phase_init(self) -> None:
        self.state.phase = Phase.INIT
        logger.info("Phase: INIT")

        # Validate config and connectivity (skip in dry-run)
        if not self.msg.dry_run and self.msg.bridge:
            logger.info("Validating configuration...")
            valid, errors = self.msg.bridge.validate()
            if not valid:
                error_msg = "Configuration validation failed:\n" + "\n".join(f"- {e}" for e in errors)
                logger.error(error_msg)
                self.msg.send(error_msg, sender="Orchestrator")
                raise RuntimeError(f"Configuration validation failed: {errors}")

        # Check for /feature or /suggest command in recent messages
        feature_override, is_suggest = self._check_for_command()

        if feature_override:
            # /feature command - skip PM suggestion
            self._workflow_type = "feature"
            self.state.feature = {
                "feature": feature_override[:60],
                "description": feature_override,
                "rationale": "Direct /feature command from user",
                "priority": "P1",
            }
            self.msg.start_thread(f"Feature specified: **{feature_override[:60]}**", sender="Orchestrator")
            return

        if is_suggest:
            # /suggest command - PM will start thread after suggesting feature
            return

        # Normal flow: PM will start thread after suggesting feature
        return

    def _phase_pm_suggest(self) -> None:
        self.state.phase = Phase.PM_SUGGEST
        logger.info("Phase: PM_SUGGEST")

        prompt = f"""Read {self.prd_path} thoroughly. Then scan the codebase and git log to understand what features are already implemented.

Identify the single highest-priority feature from the PRD that is NOT yet implemented.

Return ONLY a JSON object (no markdown fences, no extra text):
{{
  "feature": "Short feature name",
  "description": "Detailed description suitable for /speckit.specify — include enough context for a developer to understand what to build",
  "rationale": "Why this is the highest priority right now",
  "priority": "P1/P2/P3",
  "prd_section": "Which section of the PRD this comes from"
}}"""

        result = run_claude(
            prompt=prompt,
            cwd=self.project_path,
            allowed_tools=PM_TOOLS,
        )
        self.state.pm_session = result.get("session_id")

        # Parse the feature suggestion
        raw = result.get("result", "")
        try:
            # Try to extract JSON from the response
            self.state.feature = self._extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("PM returned non-JSON, using raw text")
            self.state.feature = {
                "feature": "Unknown",
                "description": raw,
                "rationale": "Could not parse PM output",
                "priority": "P1",
            }

        logger.info("PM suggested: %s", self.state.feature.get("feature"))

    def _phase_review(self) -> bool:
        self.state.phase = Phase.REVIEW
        logger.info("Phase: REVIEW")

        f = self.state.feature
        # Start thread with feature name
        self.msg.start_thread(f"{f.get('feature', 'Feature')} (Priority: {f.get('priority', '?')})", sender="PM Agent")

        self.msg.send(
            f"**Feature Suggestion**\n\n"
            f"**{f.get('feature', 'N/A')}** (Priority: {f.get('priority', '?')})\n\n"
            f"{f.get('description', '')}\n\n"
            f"_Rationale: {f.get('rationale', 'N/A')}_\n\n"
            f"Reply **approve**, **reject**, or suggest an alternative.",
            sender="PM Agent",
        )

        auto = self.cfg.get("workflow", {}).get("auto_approve", False)
        if auto:
            logger.info("Auto-approve enabled, proceeding")
            self.msg.send("Auto-approved (config: auto_approve=true)", sender="Orchestrator")
            return True

        timeout = self.cfg.get("workflow", {}).get("approval_timeout", 300)
        response = self.msg.wait_for_response(timeout=timeout)

        if response is None:
            self.msg.send(
                f"No response after {timeout}s — auto-approving.",
                sender="Orchestrator",
            )
            return True

        lower = re.sub(r"@\S+\s*", "", response.lower()).strip()
        if lower in ("reject", "no", "skip", "stop", "\U0001f44e", "-1", ":-1:", ":thumbsdown:"):
            self.msg.send("Feature rejected. Stopping.", sender="Orchestrator")
            return False

        APPROVE = {"approve", "yes", "ok", "lgtm", "go",
                   "\U0001f44d", "+1", ":+1:", ":thumbsup:"}
        if lower not in APPROVE:
            # Treat as alternative feature description
            self.msg.send(
                f"Using your input as the feature description: {response}",
                sender="Orchestrator",
            )
            self.state.feature["description"] = response
            self.state.feature["feature"] = response[:60]

        return True

    def _phase_dev_specify(self) -> None:
        self.state.phase = Phase.DEV_SPECIFY
        logger.info("Phase: DEV_SPECIFY")

        desc = self.state.feature.get("description", self.state.feature.get("feature"))
        self.msg.send(f"📋 **Specify** — {desc[:80]}...", sender="Dev Agent")

        # Note: Progress callback disabled - tool call spam not helpful in Mattermost
        result = run_claude_stream(
            prompt=f"/speckit.specify {desc}",
            cwd=self.project_path,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )
        self.state.dev_session = result.get("session_id")

        # Get a summary to post to the channel
        summary = self._get_phase_summary(
            "Summarize the specification you just created in 2-3 bullet points. "
            "Focus on: what will be built, key behaviors, and scope boundaries. Be concise."
        )
        # Truncate to avoid Mattermost message limit
        max_len = 8000
        if len(summary) > max_len:
            summary = summary[:max_len] + "\n... (truncated)"
        self.msg.send(f"📋 **Specify** — Complete\n\n{summary}", sender="Dev Agent")

    def _phase_dev_plan(self) -> None:
        self.state.phase = Phase.DEV_PLAN
        logger.info("Phase: DEV_PLAN")
        self.msg.send("📐 **Plan** — Creating technical plan...", sender="Dev Agent")

        result = run_claude_stream(
            prompt="/speckit.plan",
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

        # Get a summary to post to the channel
        summary = self._get_phase_summary(
            "Summarize the technical plan you just created in 3-5 bullet points. "
            "Include: key files to change, architecture approach, and any trade-offs. Be concise."
        )
        # Truncate to avoid Mattermost message limit
        max_len = 8000
        if len(summary) > max_len:
            summary = summary[:max_len] + "\n... (truncated)"
        self.msg.send(f"📐 **Plan** — Complete\n\n{summary}", sender="Dev Agent")

    def _phase_dev_tasks(self) -> None:
        self.state.phase = Phase.DEV_TASKS
        logger.info("Phase: DEV_TASKS")
        self.msg.send("📝 **Tasks** — Generating task list...", sender="Dev Agent")

        result = run_claude_stream(
            prompt="/speckit.tasks",
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

        # Get the task list summary
        summary = self._get_phase_summary(
            "List the implementation tasks you just generated as a numbered list. "
            "Keep each item to one line. Be concise."
        )
        # Truncate to avoid Mattermost message limit (16383 chars)
        max_len = 8000
        if len(summary) > max_len:
            summary = summary[:max_len] + "\n... (truncated)"
        self.msg.send(f"📝 **Tasks** — Complete\n\n{summary}", sender="Dev Agent")

    def _phase_plan_review(self) -> bool:
        """Checkpoint: let the human review the plan before implementation starts.

        Returns True to proceed, False to abort.
        """
        self.state.phase = Phase.PLAN_REVIEW
        logger.info("Phase: PLAN_REVIEW")

        # Mark position BEFORE posting the review message so we capture
        # any human messages that arrived during earlier phases too.
        if not self.msg.dry_run:
            # Don't reset — keep _last_seen_ts from earlier phases so we
            # capture messages sent during specify/plan/tasks.
            pass

        review_timeout = self.cfg.get("workflow", {}).get("plan_review_timeout", 60)

        self.msg.send(
            "👀 **Review** — Ready for implementation. Review the plan above.\n\n"
            "- Reply **approve** to proceed\n"
            "- Reply **reject** to stop\n"
            f"- Auto-proceeding in {review_timeout}s if no response",
            sender="Orchestrator",
        )

        auto = self.cfg.get("workflow", {}).get("auto_approve", False)
        if auto or self._auto_approve:
            logger.info("Auto-approve enabled, proceeding to implementation")
            self.msg.send("Auto-approved — starting implementation.", sender="Orchestrator")
            return True

        poll_interval = 5
        deadline = time.time() + review_timeout

        while time.time() < deadline:
            time.sleep(poll_interval)

            if self.msg.dry_run:
                response = self.msg.wait_for_response(timeout=int(deadline - time.time()))
                if response is None:
                    break
                lower = response.lower().strip()
            else:
                new = self.msg.bridge.read_new_human_messages()
                if not new:
                    continue
                # Process the first new message
                response = new[0].get("message", "").strip()
                if not response:
                    continue
                # Strip @mentions before checking keywords
                lower = re.sub(r"@\S+\s*", "", response.lower()).strip()

            APPROVE_WORDS = {"go", "approve", "yes", "ok", "lgtm", "proceed",
                             "\U0001f44d", "\U0001f44d\U0001f3fb", "\U0001f44d\U0001f3fc",
                             "\U0001f44d\U0001f3fd", "\U0001f44d\U0001f3fe", "\U0001f44d\U0001f3ff",
                             "+1", ":+1:", ":thumbsup:"}
            REJECT_WORDS = {"reject", "no", "stop", "cancel",
                            "\U0001f44e", "-1", ":-1:", ":thumbsdown:"}
            # Log what we got for debugging
            logger.info(f"Plan review response: '{response[:50]}...' (lower: '{lower}')")

            if lower in APPROVE_WORDS:
                self.msg.send("Approved — starting implementation.", sender="Orchestrator")
                return True
            if lower in REJECT_WORDS:
                self.msg.send("Plan rejected. Stopping.", sender="Orchestrator")
                return False
            # Empty response - skip
            if not lower:
                continue

            # During PLAN_REVIEW, only accept approve/reject
            # Questions during review are not supported - user must approve or reject
            # This prevents PM from answering during review (only approve/reject allowed)
            logger.info("Plan review: ignoring non-approve/reject message: %s", response[:50])
            self.msg.send(
                f"Please reply **approve** to proceed or **reject** to stop. "
                f"Auto-proceeding in {int(deadline - time.time())}s.",
                sender="Orchestrator",
            )

        # Timeout — auto-approve (yolo mode)
        self.msg.send(
            f"No objection after {review_timeout}s — proceeding with implementation.",
            sender="Orchestrator",
        )
        return True

    def _get_phase_summary(self, prompt: str) -> str:
        """Ask the dev session for a concise summary of what was just done."""
        result = run_claude(
            prompt=prompt,
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=["Read", "Glob"],
            timeout=120,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)
        return result.get("result", "(no summary available)")

    def _make_progress_callback(self, phase_name: str, report_interval: int = 3):
        """Create a progress callback that posts tool usage to Mattermost.

        Args:
            phase_name: Name of the phase (for logging)
            report_interval: Minimum seconds between progress updates

        Returns:
            A callback function suitable for run_claude_stream
        """
        last_report_time = [0.0]
        tool_count = [0]

        def callback(event: dict[str, Any]) -> None:
            event_type = event.get("type", "")

            # Helper to process a tool_use event
            def process_tool_use(tool_event: dict[str, Any]) -> None:
                nonlocal tool_count
                tool_name = tool_event.get("name", "unknown")
                tool_input = tool_event.get("input", {})

                # Filter: only show Write, Edit, Bash (skip Glob, Read, Grep, TodoWrite, etc.)
                if tool_name not in ("Bash", "Edit", "Write"):
                    return

                tool_count[0] += 1

                # Extract useful info based on tool type
                detail = ""
                if tool_name == "Bash":
                    # Show the command being run
                    detail = tool_input.get("command", "")[:60]
                elif tool_name == "Grep":
                    # Show the pattern
                    detail = f"pattern: {tool_input.get('pattern', '')}"
                elif tool_name == "Glob":
                    # Show the glob pattern
                    detail = f"pattern: {tool_input.get('pattern', '')}"
                elif tool_name == "Read":
                    # Show the file path
                    detail = tool_input.get("file_path", "")[:50]
                elif tool_name == "Edit":
                    # Show the file being edited
                    detail = tool_input.get("file_path", "")[:50]
                elif tool_name == "Write":
                    # Show the file being written
                    detail = tool_input.get("file_path", "")[:50]
                elif tool_name == "TodoWrite":
                    # Show the task description
                    detail = tool_input.get("content", "")[:40]
                elif tool_name == "NotebookEdit":
                    detail = "notebook cell"
                elif "file_path" in tool_input:
                    detail = tool_input["file_path"][:50]
                elif "path" in tool_input:
                    detail = tool_input["path"][:50]

                # Skip if no useful detail or if it's a thinking/debug tool
                if not detail or tool_name in ("Thinking", "TodoRead", "Task", "TaskOutput"):
                    return

                # Only report every N tools or if it's been a while
                now = time.time()
                should_report = (
                    tool_count[0] % report_interval == 0
                    or now - last_report_time[0] > 20
                )

                if should_report and not self.msg.dry_run:
                    # Truncate long details
                    if len(detail) > 50:
                        detail = detail[:47] + "..."
                    self.msg.send(f"🔧 {detail}", sender="Dev Agent")
                    last_report_time[0] = now

            # Check for tool_use at top level
            if event_type == "tool_use":
                process_tool_use(event)

            # Check for tool_use nested in message content (stream-json format)
            if event_type == "assistant":
                message = event.get("message", {})
                content = message.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            process_tool_use(block)

            # Log errors
            if event_type == "error":
                logger.error("Claude error: %s", event.get("error", ""))

        return callback

    def _phase_dev_implement(self) -> None:
        self.state.phase = Phase.DEV_IMPLEMENT
        logger.info("Phase: DEV_IMPLEMENT")
        self.msg.send(
            "🔨 **Implement** — Starting implementation... You can ask me product questions anytime "
            "during this phase and the PM will answer.",
            sender="Dev Agent",
        )

        prompt = """/speckit.implement

IMPORTANT: If you encounter an ambiguity or need a product decision, output ONLY this JSON (no markdown fences) and then STOP:
{"type": "question", "question": "...", "context": "...", "options": ["A: ...", "B: ..."]}

Otherwise, implement all tasks to completion."""

        # Run dev agent in a background thread so we can poll Mattermost
        # for human questions while it works.
        dev_result_holder: list[dict] = []

        def _run_dev():
            result = run_claude_stream(
                prompt=prompt,
                cwd=self.project_path,
                session_id=self.state.dev_session,
                allowed_tools=DEV_TOOLS,
                timeout=3600,
            )
            dev_result_holder.append(result)

        dev_thread = threading.Thread(target=_run_dev, daemon=True)
        dev_thread.start()

        # Poll for human questions while dev is implementing
        poll_interval = self.cfg.get("workflow", {}).get("impl_poll_interval", 15)
        if not self.msg.dry_run:
            self.msg.bridge.mark_current_position()

        while dev_thread.is_alive():
            dev_thread.join(timeout=poll_interval)
            if dev_thread.is_alive() and not self.msg.dry_run:
                self._check_for_human_questions()

        # Dev agent finished — process its result
        if dev_result_holder:
            result = dev_result_holder[0]
            self.state.dev_session = result.get("session_id", self.state.dev_session)
            raw = result.get("result", "")

            # Check if dev asked a question (it stopped to ask)
            if '"type": "question"' in raw or '"type":"question"' in raw:
                self._handle_dev_question(raw)

        self.msg.send("🔨 **Implement** — Complete", sender="Dev Agent")

    def _check_for_human_questions(self) -> None:
        """Check Mattermost for human messages and route them appropriately.

        Implementation/status questions go to Dev Agent.
        Product/requirements questions go to PM Agent.
        """
        new = self.msg.bridge.read_new_human_messages()
        for msg in new:
            text = msg.get("message", "").strip()
            if not text:
                continue
            logger.info("Human question during impl: %s", text[:100])

            # Heuristic: route implementation questions to Dev, product questions to PM
            impl_keywords = ["next", "task", "progress", "status", "working on", "when will",
                             "how", "why is it", "why does", "todo", "priority"]
            product_keywords = ["should", "can you", "could you", "what's the", " PRD",
                                "requirement", "spec", "feature", "design", "api", "data model"]

            text_lower = text.lower()
            is_impl = any(kw in text_lower for kw in impl_keywords)
            is_product = any(kw in text_lower for kw in product_keywords)

            if is_impl and not is_product:
                # Route to Dev Agent for implementation questions
                self._answer_impl_question(text)
            else:
                # Route to PM Agent for product questions
                self._answer_human_question(text)

    def _check_for_command(self) -> tuple[str | None, bool]:
        """Check for /feature or /suggest commands in recent channel messages.

        Looks for messages like:
        - /feature build a todo list - skip PM, build directly
        - /suggest - ask PM to suggest a feature from PRD

        Returns:
            tuple of (feature_text, is_suggest)
            - feature_text: description if /feature command, None otherwise
            - is_suggest: True if /suggest command found
        """
        if self.msg.dry_run or not self.msg.bridge:
            return None, False

        # Get bot user IDs to skip
        bot_user_ids = self.msg.bridge.bot_user_ids

        try:
            # Read recent messages (last 5)
            posts = self.msg.bridge.read_posts(limit=5)
            for post in posts:
                msg_text = post.get("message", "").strip()
                user_id = post.get("user_id", "")

                # Skip bot messages
                if user_id in bot_user_ids:
                    continue
                if not msg_text:
                    continue

                # Check for /suggest command
                if msg_text.startswith("/suggest") or msg_text.startswith("/pm"):
                    logger.info("Found /suggest command")
                    return None, True

                # Check for /feature command
                if msg_text.startswith("/feature ") or msg_text.startswith("/feature\n"):
                    feature = msg_text.replace("/feature", "", 1).strip()
                    logger.info("Found /feature command: %s", feature[:50])
                    return feature, False

                # Check for "feature:" prefix (after @mention or standalone)
                lower = msg_text.lower()
                if lower.startswith("feature:") or lower.startswith("feature "):
                    feature = msg_text.split(":", 1)[1].strip() if ":" in msg_text else msg_text.split(" ", 1)[1].strip()
                    if feature:
                        logger.info("Found feature: command: %s", feature[:50])
                        return feature, False
        except Exception as e:
            logger.warning("Error checking for command: %s", e)

        return None, False

    def _answer_human_question(self, question: str) -> None:
        """Have the PM agent answer a human question posted in Mattermost."""
        pm_prompt = (
            f"A team member asks the following question during feature implementation:\n\n"
            f"\"{question}\"\n\n"
            f"Answer based on the PRD (docs/PRD.md) and project context. "
            f"Be concise and helpful."
        )
        pm_result = run_claude(
            prompt=pm_prompt,
            cwd=self.project_path,
            session_id=self.state.pm_session,
            allowed_tools=PM_TOOLS,
            timeout=3600,
        )
        self.state.pm_session = pm_result.get("session_id", self.state.pm_session)
        answer = pm_result.get("result", "I couldn't determine an answer from the PRD.")
        self.msg.send(answer, sender="PM Agent")

    def _answer_impl_question(self, question: str) -> None:
        """Have the Dev agent answer an implementation question posted in Mattermost."""
        impl_prompt = (
            f"A team member asks the following question about the current implementation:\n\n"
            f"\"{question}\"\n\n"
            f"Answer based on what you're currently working on. "
            f"Be concise and helpful. Mention which task you're on if relevant."
        )
        dev_result = run_claude(
            prompt=impl_prompt,
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )
        self.state.dev_session = dev_result.get("session_id", self.state.dev_session)
        answer = dev_result.get("result", "I'm currently implementing - could you rephrase?")
        self.msg.send(answer, sender="Dev Agent")

    def _handle_dev_question(self, raw: str) -> None:
        """Route a developer question through PM and/or Mattermost."""
        try:
            question = self._extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Could not parse dev question JSON")
            self.msg.send(f"Dev had a question but I couldn't parse it:\n{raw[:500]}", sender="Orchestrator")
            return

        q_text = question.get("question", "Unknown question")
        q_context = question.get("context", "")
        q_options = question.get("options", [])

        # Post question to Mattermost
        options_text = "\n".join(f"  - {opt}" for opt in q_options) if q_options else ""
        self.msg.send(
            f"**Question:**\n{q_text}\n\n"
            f"_Context: {q_context}_\n\n"
            f"Options:\n{options_text}\n\n"
            f"Asking PM Agent for recommendation...",
            sender="Dev Agent",
        )

        # Ask PM Agent to answer
        pm_prompt = (
            f"The developer is implementing a feature and has this question:\n\n"
            f"Question: {q_text}\n"
            f"Context: {q_context}\n"
            f"Options: {', '.join(q_options)}\n\n"
            f"Based on the PRD and project goals, what is the right answer? "
            f"Be concise and decisive."
        )
        pm_result = run_claude(
            prompt=pm_prompt,
            cwd=self.project_path,
            session_id=self.state.pm_session,
            allowed_tools=PM_TOOLS,
            timeout=3600,
        )
        self.state.pm_session = pm_result.get("session_id", self.state.pm_session)
        pm_answer = pm_result.get("result", "No answer from PM")

        self.msg.send(f"**Recommendation:** {pm_answer}", sender="PM Agent")

        # Wait briefly for human override
        self.msg.send(
            "Reply within 60s to override, or I'll use the PM's recommendation.",
            sender="Orchestrator",
        )
        human = self.msg.wait_for_response(
            timeout=self.cfg.get("workflow", {}).get("question_timeout", 120)
        )
        answer = human if human else pm_answer

        # Feed answer back to dev agent
        resume_prompt = f"The answer to your question is: {answer}\n\nPlease continue with implementation."
        result = run_claude(
            prompt=resume_prompt,
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

    def _phase_create_pr(self) -> None:
        self.state.phase = Phase.CREATE_PR
        logger.info("Phase: CREATE_PR")
        self.msg.send("🔀 **PR** — Creating pull request...", sender="Dev Agent")

        prompt = """Create a pull request for all the changes on this branch.

1. Make sure all changes are committed
2. Push the branch to the remote
3. Create a PR using: gh pr create --title "..." --body "..."
4. Return ONLY the PR URL as plain text (no markdown, no extra text)"""

        result = run_claude(
            prompt=prompt,
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=3600,
        )

        self.state.pr_url = result.get("result", "").strip()
        logger.info("PR URL: %s", self.state.pr_url)

    def _phase_pm_learn(self) -> None:
        """Have PM agent write a learning entry to .agent/product-manager.md journal."""
        self.state.phase = Phase.PM_LEARN
        logger.info("Phase: PM_LEARN")
        self.msg.send("📖 **Learn** — Recording learnings...", sender="PM Agent")

        feature_name = self.state.feature.get("feature", "Unknown")

        prompt = f"""After implementing the feature "{feature_name}", analyze what was learned and write a journal entry to `.agent/product-manager.md`.

1. First, read the existing `.agent/product-manager.md` if it exists to see the format
2. Add a new entry at the top with today's date
3. The format should be:

## YYYY-MM-DD - Feature Name
**Learning:** What did you learn during implementation? What was expensive, tricky, or surprising?
**Action:** What would you do differently next time? What patterns should be followed?

4. Write the new entry to the file using the Write tool

Be specific about:
- Performance issues found and how they were fixed
- Architecture decisions and trade-offs
- What worked well vs what was painful
- Recommendations for future work on this codebase"""

        try:
            result = run_claude(
                prompt=prompt,
                cwd=self.original_path,
                session_id=self.state.pm_session,
                allowed_tools=PM_TOOLS + ["Write"],
                timeout=300,
            )
            self.state.pm_session = result.get("session_id", self.state.pm_session)
        except RuntimeError as e:
            # Session expired, create new one
            logger.warning(f"PM session expired, creating new session: {e}")
            self.state.pm_session = None
            result = run_claude(
                prompt=prompt,
                cwd=self.original_path,
                session_id=None,
                allowed_tools=PM_TOOLS + ["Write"],
                timeout=300,
            )
            self.state.pm_session = result.get("session_id")

        logger.info("Learning recorded to journal")

    def _phase_done(self) -> None:
        self.state.phase = Phase.DONE
        logger.info("Phase: DONE")

        # Clean up worktree after PR is created
        self._cleanup_worktree()

        self._post_summary()

        if self.state.pr_url:
            # Get user mention from config (e.g., "@sbhavani")
            user_mention = self.cfg.get("workflow", {}).get("user_mention", "")
            if user_mention:
                self.msg.send(f"{user_mention} PR created: {self.state.pr_url}", sender="Dev Agent")
            else:
                self.msg.send(f"PR created: {self.state.pr_url}", sender="Dev Agent")
        else:
            self.msg.send("Workflow complete (no PR URL captured).", sender="Orchestrator")

    # -- Summary ---------------------------------------------------------------

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """Format seconds into a human-readable duration string."""
        s = int(round(seconds))
        if s < 60:
            return f"{s}s"
        m, s = divmod(s, 60)
        return f"{m}m {s}s" if s else f"{m}m"

    def _post_summary(self, error: str | None = None) -> None:
        """Format and send a workflow summary to Mattermost."""
        feature_name = self.state.feature.get("feature", "N/A")

        total = time.time() - self._run_start_time if self._run_start_time is not None else 0
        duration_str = self._fmt_duration(total)

        if error:
            status = f"Failed at {self.state.phase.name}"
        else:
            status = "Complete"

        # Build timing table
        rows = []
        for phase_name, dur in self._phase_timings:
            rows.append(f"| {phase_name} | {self._fmt_duration(dur)} |")
        table = (
            "| Phase | Duration |\n"
            "|:------|:---------|\n"
            + "\n".join(rows)
        )

        if error:
            summary = (
                f"**Workflow Summary**\n"
                f"Feature: {feature_name}\n"
                f"Status: {status} | Duration: {duration_str}\n\n"
                f"{table}\n\n"
                f"Error: {error}\n"
                f"Run with `--resume` to continue."
            )
        else:
            pr_line = f"\nPR: {self.state.pr_url}" if self.state.pr_url else ""
            summary = (
                f"**Workflow Summary**\n"
                f"Feature: {feature_name}\n"
                f"Status: {status} | Duration: {duration_str}\n\n"
                f"{table}"
                f"{pr_line}"
            )

        logger.info("Workflow summary:\n%s", summary)
        self.msg.send(summary, sender="Orchestrator")

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract a JSON object from text that may contain surrounding prose."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON within the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError("No JSON object found in text")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

__version__ = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Team Orchestrator")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of Mattermost")
    parser.add_argument("--loop", action="store_true", help="Keep running for multiple features")
    parser.add_argument("--feature", type=str, default=None,
                        help="Skip PM agent and directly implement this feature description")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last saved state (.agent-team-state.json)")
    parser.add_argument("--approve", action="store_true",
                        help="Resume and auto-approve the plan (skip review)")
    parser.add_argument("--project", type=str, default=None,
                        help="Project name from config (for multi-project setups)")
    parser.add_argument("--channel", type=str, default=None,
                        help="Override Mattermost channel ID")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--show-state", action="store_true", help="Print current state and exit")
    args = parser.parse_args()

    # Handle --version flag
    if args.version:
        print(f"agent-team orchestrator v{__version__}")
        return

    if args.resume and args.feature:
        parser.error("--resume and --feature are mutually exclusive")

    config_path = args.config
    if not os.path.exists(config_path):
        # Try relative to script directory
        config_path = os.path.join(os.path.dirname(__file__), args.config)
    config = load_config(config_path)

    # Handle --show-state flag
    if args.show_state:
        try:
            project_path, prd_path, project_channel_id = resolve_project_config(config, args.project)
        except ValueError as e:
            # Try default path if project not specified
            project_path = config.get("project", {}).get("path", ".")

        state_file = os.path.join(project_path, STATE_FILE)
        if os.path.exists(state_file):
            with open(state_file) as f:
                state = json.load(f)
            import pprint
            print("Current state:")
            pprint.pprint(state)
        else:
            print("No saved state found.")
        return

    # Resolve project config (supports single project or multi-project mode)
    try:
        project_path, prd_path, project_channel_id = resolve_project_config(config, args.project)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Use --channel override, project channel_id, or fallback to global config
    channel_id = args.channel or project_channel_id or config.get("mattermost", {}).get("channel_id")

    if args.dry_run:
        messenger = Messenger(bridge=None, dry_run=True)
    else:
        mm = config["mattermost"]
        bridge = MattermostBridge(
            ssh_host=config["openclaw"]["ssh_host"],
            channel_id=channel_id,
            mattermost_url=mm.get("url", "http://localhost:8065"),
            dev_bot_token=mm["dev_bot_token"],
            dev_bot_user_id=mm.get("dev_bot_user_id", ""),
            pm_bot_token=mm.get("pm_bot_token", ""),
            pm_bot_user_id=mm.get("pm_bot_user_id", ""),
            openclaw_account=config["openclaw"].get("openclaw_account"),
        )
        messenger = Messenger(bridge=bridge)

    orchestrator = Orchestrator(config, messenger, project_path=project_path, prd_path=prd_path)

    if args.resume:
        saved = orchestrator._load_state()
        if saved is None:
            print("Error: No saved state found. Run without --resume first.")
            sys.exit(1)
        # Restore state from file
        orchestrator.state.phase = Phase[saved["phase"]]
        orchestrator.state.feature = saved.get("feature", {})
        orchestrator.state.pm_session = saved.get("pm_session")
        orchestrator.state.dev_session = saved.get("dev_session")
        orchestrator.state.pr_url = saved.get("pr_url")
        orchestrator._workflow_type = saved.get("workflow_type", "normal")
        orchestrator._started_at = saved.get("started_at")
        # Restore paths from saved state
        if saved.get("original_path"):
            orchestrator.original_path = saved["original_path"]
        if saved.get("worktree_path"):
            orchestrator.worktree_path = saved["worktree_path"]
            orchestrator.project_path = saved["worktree_path"]
        # Restore thread root ID so messages continue in the same thread
        if saved.get("thread_root_id"):
            orchestrator.msg._root_id = saved["thread_root_id"]
            logger.info("Restored thread: %s", saved["thread_root_id"])
        orchestrator._resuming = True
        # If --approve is set, skip to implementation
        if args.approve:
            orchestrator._auto_approve = True
            orchestrator.msg.send(
                f"Resuming from **{saved['phase']}** phase (auto-approve enabled)",
                sender="Orchestrator",
            )
        else:
            orchestrator.msg.send(
                f"Resuming from **{saved['phase']}** phase",
                sender="Orchestrator",
            )
        orchestrator.run(loop=False)
    elif args.feature:
        # Skip PM — inject the feature directly and use the feature sequence
        orchestrator._workflow_type = "feature"
        orchestrator.state.feature = {
            "feature": args.feature[:60],
            "description": args.feature,
            "rationale": "Manually specified via --feature flag",
            "priority": "P1",
        }
        # Start a thread for this feature
        orchestrator.msg.start_thread(
            f"Feature specified via CLI: **{args.feature[:60]}**",
            sender="Orchestrator",
        )
        orchestrator.run(loop=False)
    else:
        loop = args.loop or config.get("workflow", {}).get("loop", False)
        orchestrator.run(loop=loop)


if __name__ == "__main__":
    main()
