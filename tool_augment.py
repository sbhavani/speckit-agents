#!/usr/bin/env python3
"""Tool-augmented discovery and validation layer for the orchestrator.

Probes the target codebase before each dev phase (discovery) and validates
artifacts after each phase (validation).  Findings are injected as context
into the next phase's prompt and logged to JSONL for analysis.

Usage:
    from tool_augment import ToolAugmentor, ToolAugmentConfig

    cfg = ToolAugmentConfig.from_dict(config["workflow"]["tool_augmentation"])
    aug = ToolAugmentor(project_path, cfg, run_id, run_claude_fn=run_claude)

    pre  = aug.run_pre_hook(Phase.DEV_SPECIFY, state)
    # ... run phase ...
    post = aug.run_post_hook(Phase.DEV_SPECIFY, state)
    # ... later ...
    aug.finalize("success")
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import redis

logger = logging.getLogger(__name__)


# Re-use the Phase enum from orchestrator at runtime, but keep a local
# reference so the module can be imported and tested standalone.
# Callers pass Phase values; we match on .name strings internally.

# ---------------------------------------------------------------------------
# Read-only tool sets for hooks
# ---------------------------------------------------------------------------

DISCOVERY_TOOLS = [
    "Read", "Glob", "Grep",
    "Bash(git log *)", "Bash(git diff *)", "Bash(ls *)",
]

VALIDATION_TOOLS = DISCOVERY_TOOLS + [
    "Bash(pytest *)", "Bash(ruff *)",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ToolAugmentConfig:
    """Configuration for the tool-augmentation layer."""
    enabled: bool = False
    pre_stages: bool = True
    post_stages: bool = True
    run_tests_before_impl: bool = True
    run_tests_after_impl: bool = True
    timeout_per_hook: int = 120
    log_dir: str = "logs/augment"
    redis_url: str | None = None  # Redis for logging (faster than JSONL)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ToolAugmentConfig":
        if not d:
            return cls()
        return cls(
            enabled=d.get("enabled", False),
            pre_stages=d.get("pre_stages", True),
            post_stages=d.get("post_stages", True),
            run_tests_before_impl=d.get("run_tests_before_impl", True),
            run_tests_after_impl=d.get("run_tests_after_impl", True),
            timeout_per_hook=d.get("timeout_per_hook", 120),
            log_dir=d.get("log_dir", "logs/augment"),
            redis_url=d.get("redis_url"),
        )


# ---------------------------------------------------------------------------
# Redis/JSONL Logger
# ---------------------------------------------------------------------------

class ToolAugmentLog:
    """Logger for augmentation records - uses Redis if available, falls back to JSONL."""

    def __init__(self, log_dir: str, run_id: str, redis_url: str | None = None):
        self.log_dir = Path(log_dir)
        self.run_id = run_id
        self.redis_url = redis_url
        self._path = self.log_dir / f"run_{run_id}.jsonl"
        self._redis: redis.Redis | None = None

        # Try to connect to Redis if URL provided
        if redis_url:
            try:
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("Using Redis for augmentation logging: %s", redis_url)
            except Exception as e:
                logger.warning("Failed to connect to Redis: %s, falling back to JSONL", e)
                self._redis = None

        # Ensure log directory exists for JSONL fallback
        if not self._redis:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record_type: str, **kwargs: Any) -> None:
        """Write a single record - to Redis if available, otherwise JSONL."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "record_type": record_type,
            **kwargs,
        }

        if self._redis:
            # Push to Redis list (FIFO queue per run)
            key = f"augment:run:{self.run_id}"
            self._redis.rpush(key, json.dumps(record, default=str))
            # Set TTL of 7 days for retention
            self._redis.expire(key, 7 * 24 * 60 * 60)
        else:
            # Fallback to JSONL
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")

    def write_tool_call(self, phase: str, hook_type: str, prompt: str, duration_ms: float, findings: dict) -> None:
        self.write(
            "tool_call",
            phase=phase,
            hook_type=hook_type,
            prompt_preview=prompt[:200],
            duration_ms=round(duration_ms, 1),
            findings=findings,
        )

    def write_hook_summary(self, phase: str, hook_type: str, duration_ms: float, findings: dict) -> None:
        self.write(
            "hook_summary",
            phase=phase,
            hook_type=hook_type,
            duration_ms=round(duration_ms, 1),
            findings=findings,
        )

    def write_run_summary(self, outcome: str, phases_augmented: list[str], total_hooks: int, total_duration_ms: float) -> None:
        self.write(
            "run_summary",
            outcome=outcome,
            phases_augmented=phases_augmented,
            total_hooks=total_hooks,
            total_duration_ms=round(total_duration_ms, 1),
        )


# ---------------------------------------------------------------------------
# Hook prompts
# ---------------------------------------------------------------------------

_PRE_SPECIFY_PROMPT = """\
You are a codebase analyst. Examine this project and return a JSON object with:
{{
  "similar_features": ["list of existing features similar to the one being specified"],
  "conventions": "coding conventions observed (naming, file structure, patterns)",
  "architecture_pattern": "overall architecture pattern (MVC, layered, microservices, etc.)",
  "testing_framework": "test framework and patterns used (pytest, unittest, etc.)",
  "suggested_location": "where new feature code should live based on existing structure",
  "warnings": ["any concerns about adding this feature"]
}}

Feature being specified: {feature_desc}

Search for similar features, read key config files, check git log for recent feature additions, and examine the test structure. Return ONLY the JSON object."""

_PRE_PLAN_PROMPT = """\
You are a dependency verifier. The following spec was just created. Verify against the actual codebase and return a JSON object with:
{{
  "verified_dependencies": ["dependencies that exist and are available"],
  "missing_dependencies": ["referenced modules/packages that don't exist"],
  "test_framework": "test framework in use",
  "middleware_patterns": "middleware or plugin patterns used",
  "import_patterns": "import conventions (absolute, relative, aliases)"
}}

Search the codebase for the dependencies and patterns referenced in the spec. Check package.json/pyproject.toml/requirements.txt for installed packages. Return ONLY the JSON object."""

_PRE_TASKS_PROMPT = """\
You are a plan validator. Verify the implementation plan against the actual codebase and return a JSON object with:
{{
  "verified_paths": ["file paths from the plan that already exist"],
  "new_paths_needed": ["file paths that will need to be created"],
  "feasibility_score": 0.0-1.0,
  "blockers": ["anything that would prevent implementation"],
  "warnings": ["non-blocking concerns"]
}}

Check if the files referenced in the plan exist. Verify library availability. Check for external service references. Return ONLY the JSON object."""

_PRE_IMPLEMENT_PROMPT = """\
You are a pre-flight checker. Run pre-implementation checks and return a JSON object with:
{{
  "tests_baseline": "summary of existing test suite results",
  "tests_green": true/false,
  "git_clean": true/false,
  "git_branch": "current branch name",
  "pre_flight_passed": true/false
}}

Run `pytest --tb=line -q` to check the test baseline (if pytest is configured). Check `git status` for cleanliness and `git branch` for the current branch. Return ONLY the JSON object."""

_POST_SPECIFY_PROMPT = """\
You are a spec validator. Check the specification that was just created against the actual codebase and return a JSON object with:
{{
  "referenced_but_missing": ["modules/classes referenced in spec that don't exist in codebase"],
  "dependency_gaps": ["external deps referenced but not installed"],
  "naming_conflicts": ["names that conflict with existing code"],
  "validation_passed": true/false
}}

Read the spec file, then grep/glob the codebase for each reference. Return ONLY the JSON object."""

_POST_PLAN_PROMPT = """\
You are a plan validator. Check the implementation plan against the codebase and return a JSON object with:
{{
  "files_exist": ["planned files that already exist"],
  "files_missing": ["planned files that need creation"],
  "libraries_to_add": ["libraries referenced but not installed"],
  "consistency_issues": ["inconsistencies between plan and codebase"],
  "validation_passed": true/false
}}

Read the plan, then verify file paths and library references. Return ONLY the JSON object."""

_POST_TASKS_PROMPT = """\
You are a task validator. Check the generated task list and return a JSON object with:
{{
  "ordering_issues": ["tasks that appear to be in wrong order"],
  "missing_file_refs": ["file references in tasks that don't exist and aren't planned"],
  "dependency_issues": ["task dependency problems"],
  "validation_passed": true/false
}}

Read the tasks file, check references against the codebase. Return ONLY the JSON object."""

_POST_IMPLEMENT_PROMPT = """\
You are a quality checker. Run post-implementation validation and return a JSON object with:
{{
  "tests_result": "test suite output summary",
  "tests_green": true/false,
  "lint_issues": ["linting issues found"],
  "files_changed": 0,
  "quality_score": 0.0-1.0,
  "validation_passed": true/false
}}

Run `pytest --tb=short -q` to check tests. Run `ruff check .` for linting. Check `git diff --stat` for files changed. Count TODO/FIXME comments in changed files. Return ONLY the JSON object."""


# ---------------------------------------------------------------------------
# ToolAugmentor
# ---------------------------------------------------------------------------

# Type alias for the run_claude callable
RunClaudeFn = Callable[..., dict]


class ToolAugmentor:
    """Runs pre/post hooks around orchestrator phases using Claude with read-only tools."""

    # Map phase names to hook method names
    PRE_HOOKS: dict[str, str] = {
        "DEV_SPECIFY": "pre_specify",
        "DEV_PLAN": "pre_plan",
        "DEV_TASKS": "pre_tasks",
        "DEV_IMPLEMENT": "pre_implement",
    }

    POST_HOOKS: dict[str, str] = {
        "DEV_SPECIFY": "post_specify",
        "DEV_PLAN": "post_plan",
        "DEV_TASKS": "post_tasks",
        "DEV_IMPLEMENT": "post_implement",
    }

    def __init__(
        self,
        project_path: str,
        config: ToolAugmentConfig,
        run_id: str,
        run_claude_fn: RunClaudeFn,
    ):
        self.project_path = project_path
        self.config = config
        self.run_id = run_id
        self._run_claude = run_claude_fn
        self._log = ToolAugmentLog(config.log_dir, run_id, config.redis_url)
        self._phases_augmented: list[str] = []
        self._total_hooks = 0
        self._total_duration_ms = 0.0

    @property
    def log(self) -> ToolAugmentLog:
        return self._log

    def run_pre_hook(self, phase: Any, state: Any) -> dict | None:
        """Run discovery hook before a phase. Returns findings dict or None."""
        if not self.config.enabled or not self.config.pre_stages:
            return None

        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        hook_name = self.PRE_HOOKS.get(phase_name)
        if not hook_name:
            return None

        logger.info("Running pre-hook: %s for phase %s", hook_name, phase_name)
        method = getattr(self, f"_{hook_name}", None)
        if not method:
            logger.warning("No implementation for pre-hook: %s", hook_name)
            return None

        t0 = time.time()
        try:
            findings = method(state)
        except Exception as e:
            logger.warning("Pre-hook %s failed: %s", hook_name, e)
            findings = {"error": str(e), "validation_passed": False}
        duration_ms = (time.time() - t0) * 1000

        self._log.write_hook_summary(phase_name, "pre", duration_ms, findings or {})
        self._total_hooks += 1
        self._total_duration_ms += duration_ms
        if phase_name not in self._phases_augmented:
            self._phases_augmented.append(phase_name)

        return findings

    def run_post_hook(self, phase: Any, state: Any) -> dict | None:
        """Run validation hook after a phase. Returns findings dict or None."""
        if not self.config.enabled or not self.config.post_stages:
            return None

        phase_name = phase.name if hasattr(phase, "name") else str(phase)
        hook_name = self.POST_HOOKS.get(phase_name)
        if not hook_name:
            return None

        logger.info("Running post-hook: %s for phase %s", hook_name, phase_name)
        method = getattr(self, f"_{hook_name}", None)
        if not method:
            logger.warning("No implementation for post-hook: %s", hook_name)
            return None

        t0 = time.time()
        try:
            findings = method(state)
        except Exception as e:
            logger.warning("Post-hook %s failed: %s", hook_name, e)
            findings = {"error": str(e), "validation_passed": False}
        duration_ms = (time.time() - t0) * 1000

        self._log.write_hook_summary(phase_name, "post", duration_ms, findings or {})
        self._total_hooks += 1
        self._total_duration_ms += duration_ms

        return findings

    def finalize(self, outcome: str) -> None:
        """Write run summary record."""
        self._log.write_run_summary(
            outcome=outcome,
            phases_augmented=self._phases_augmented,
            total_hooks=self._total_hooks,
            total_duration_ms=self._total_duration_ms,
        )
        logger.info(
            "Augmentation complete: %d hooks, %.1fs total, phases: %s",
            self._total_hooks,
            self._total_duration_ms / 1000,
            ", ".join(self._phases_augmented) or "none",
        )

    # -- Pre-hooks -------------------------------------------------------------

    def _pre_specify(self, state: Any) -> dict:
        feature_desc = ""
        if hasattr(state, "feature") and isinstance(state.feature, dict):
            feature_desc = state.feature.get("description", state.feature.get("feature", ""))
        prompt = _PRE_SPECIFY_PROMPT.format(feature_desc=feature_desc)
        return self._invoke_claude(prompt, "DEV_SPECIFY", "pre", DISCOVERY_TOOLS)

    def _pre_plan(self, state: Any) -> dict:
        return self._invoke_claude(_PRE_PLAN_PROMPT, "DEV_PLAN", "pre", DISCOVERY_TOOLS)

    def _pre_tasks(self, state: Any) -> dict:
        return self._invoke_claude(_PRE_TASKS_PROMPT, "DEV_TASKS", "pre", DISCOVERY_TOOLS)

    def _pre_implement(self, state: Any) -> dict:
        tools = DISCOVERY_TOOLS[:]
        if self.config.run_tests_before_impl:
            tools.append("Bash(pytest *)")
        return self._invoke_claude(_PRE_IMPLEMENT_PROMPT, "DEV_IMPLEMENT", "pre", tools)

    # -- Post-hooks ------------------------------------------------------------

    def _post_specify(self, state: Any) -> dict:
        return self._invoke_claude(_POST_SPECIFY_PROMPT, "DEV_SPECIFY", "post", DISCOVERY_TOOLS)

    def _post_plan(self, state: Any) -> dict:
        return self._invoke_claude(_POST_PLAN_PROMPT, "DEV_PLAN", "post", DISCOVERY_TOOLS)

    def _post_tasks(self, state: Any) -> dict:
        return self._invoke_claude(_POST_TASKS_PROMPT, "DEV_TASKS", "post", DISCOVERY_TOOLS)

    def _post_implement(self, state: Any) -> dict:
        tools = DISCOVERY_TOOLS[:]
        if self.config.run_tests_after_impl:
            tools.extend(["Bash(pytest *)", "Bash(ruff *)"])
        return self._invoke_claude(_POST_IMPLEMENT_PROMPT, "DEV_IMPLEMENT", "post", tools)

    # -- Claude invocation -----------------------------------------------------

    def _invoke_claude(self, prompt: str, phase: str, hook_type: str, tools: list[str]) -> dict:
        """Invoke Claude with read-only tools and parse JSON findings."""
        t0 = time.time()

        result = self._run_claude(
            prompt=prompt,
            cwd=self.project_path,
            allowed_tools=tools,
            timeout=self.config.timeout_per_hook,
        )

        duration_ms = (time.time() - t0) * 1000
        raw = result.get("result", "")

        findings = self._parse_json_findings(raw)

        self._log.write_tool_call(phase, hook_type, prompt, duration_ms, findings)

        return findings

    @staticmethod
    def _parse_json_findings(text: str) -> dict:
        """Extract a JSON object from Claude's response text."""
        # Try direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find JSON within markdown fences
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # Try to find a JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                pass

        # Fallback: return raw text as a finding
        return {"raw_response": text[:500], "parse_error": True}
