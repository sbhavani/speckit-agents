#!/usr/bin/env python3
"""Agent Team Orchestrator — PM + Developer agents collaborating via Mattermost.

Usage:
    python orchestrator.py                     # Run with config.yaml
    python orchestrator.py --config my.yaml    # Custom config
    python orchestrator.py --dry-run           # Skip Mattermost, print to stdout
    python orchestrator.py --loop              # Keep suggesting features after each PR
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
from enum import Enum, auto
from pathlib import Path

import yaml

from mattermost_bridge import MattermostBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


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
    DONE = auto()


@dataclass
class WorkflowState:
    phase: Phase = Phase.INIT
    feature: dict = field(default_factory=dict)
    pm_session: str | None = None
    dev_session: str | None = None
    pr_url: str | None = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Allow local overrides
    local = Path(path).with_suffix(".local.yaml")
    if local.exists():
        with open(local) as f:
            local_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, local_cfg)
    return cfg


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
) -> dict:
    """Run `claude -p` and return parsed JSON output.

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
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as e:
        logger.warning("claude -p timed out after %ds, capturing partial output", timeout)
        partial = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        # Try to salvage session_id from partial output
        try:
            parsed = json.loads(partial)
            return parsed
        except (json.JSONDecodeError, ValueError):
            return {"result": partial.strip(), "session_id": session_id, "_timeout": True}

    if result.returncode != 0:
        logger.error("claude stderr: %s", result.stderr[:500])
        raise RuntimeError(f"claude -p failed: {result.stderr[:500]}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # Sometimes output is plain text even with --output-format json
        return {"result": result.stdout.strip(), "session_id": session_id}


# ---------------------------------------------------------------------------
# Messenger — abstracts dry-run vs real Mattermost
# ---------------------------------------------------------------------------

class Messenger:
    """Unified interface for posting messages (Mattermost or stdout)."""

    def __init__(self, bridge: MattermostBridge | None, dry_run: bool = False):
        self.bridge = bridge
        self.dry_run = dry_run

    def send(self, message: str, sender: str = "Orchestrator") -> None:
        if self.dry_run:
            print(f"\n--- [{sender}] ---\n{message}\n")
        else:
            self.bridge.send(message, sender=sender)

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
    def __init__(self, config: dict, messenger: Messenger):
        self.cfg = config
        self.msg = messenger
        self.project_path = config["project"]["path"]
        self.prd_path = config["project"]["prd_path"]
        self.state = WorkflowState()

    def run(self, loop: bool = False) -> None:
        """Execute the full workflow."""
        while True:
            try:
                self._run_once()
            except KeyboardInterrupt:
                self.msg.send("Workflow interrupted by operator.", sender="Orchestrator")
                break
            except Exception as e:
                logger.exception("Workflow error")
                self.msg.send(f"Workflow error: {e}", sender="Orchestrator")
                break

            if not loop:
                break
            # Reset state for next iteration
            self.state = WorkflowState()
            self.msg.send("Starting next feature cycle...", sender="Orchestrator")

    def _run_once(self) -> None:
        self._phase_init()
        self._phase_pm_suggest()
        if not self._phase_review():
            return  # rejected
        self._phase_dev_specify()
        self._phase_dev_plan()
        self._phase_dev_tasks()
        if not self._phase_plan_review():
            return  # rejected
        self._phase_dev_implement()
        self._phase_create_pr()
        self._phase_done()

    # -- Phases ----------------------------------------------------------------

    def _phase_init(self) -> None:
        self.state.phase = Phase.INIT
        logger.info("Phase: INIT")
        self.msg.send("Starting feature prioritization...", sender="PM Agent")

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
        self.msg.send(f"Running speckit specify for: {desc[:100]}...", sender="Dev Agent")

        result = run_claude(
            prompt=f"/speckit.specify {desc}",
            cwd=self.project_path,
            allowed_tools=DEV_TOOLS,
            timeout=1800,
        )
        self.state.dev_session = result.get("session_id")

        # Get a summary to post to the channel
        summary = self._get_phase_summary(
            "Summarize the specification you just created in 2-3 bullet points. "
            "Focus on: what will be built, key behaviors, and scope boundaries. Be concise."
        )
        self.msg.send(f"**Specification complete.**\n\n{summary}", sender="Dev Agent")

    def _phase_dev_plan(self) -> None:
        self.state.phase = Phase.DEV_PLAN
        logger.info("Phase: DEV_PLAN")
        self.msg.send("Creating technical plan...", sender="Dev Agent")

        result = run_claude(
            prompt="/speckit.plan",
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=1800,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

        # Get a summary to post to the channel
        summary = self._get_phase_summary(
            "Summarize the technical plan you just created in 3-5 bullet points. "
            "Include: key files to change, architecture approach, and any trade-offs. Be concise."
        )
        self.msg.send(f"**Technical plan complete.**\n\n{summary}", sender="Dev Agent")

    def _phase_dev_tasks(self) -> None:
        self.state.phase = Phase.DEV_TASKS
        logger.info("Phase: DEV_TASKS")
        self.msg.send("Generating task list...", sender="Dev Agent")

        result = run_claude(
            prompt="/speckit.tasks",
            cwd=self.project_path,
            session_id=self.state.dev_session,
            allowed_tools=DEV_TOOLS,
            timeout=1800,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

        # Get the task list summary
        summary = self._get_phase_summary(
            "List the implementation tasks you just generated as a numbered list. "
            "Keep each item to one line. Be concise."
        )
        self.msg.send(f"**Task list generated.**\n\n{summary}", sender="Dev Agent")

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
            "**Ready for implementation.** Review the plan above.\n\n"
            "- Ask any questions and the PM will answer\n"
            "- Reply **reject** to stop\n"
            f"- Auto-proceeding in {review_timeout}s if no objection",
            sender="Orchestrator",
        )

        auto = self.cfg.get("workflow", {}).get("auto_approve", False)
        if auto:
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
            if lower in APPROVE_WORDS:
                self.msg.send("Approved — starting implementation.", sender="Orchestrator")
                return True
            if lower in REJECT_WORDS:
                self.msg.send("Plan rejected. Stopping.", sender="Orchestrator")
                return False

            # Treat as a question — route to PM
            logger.info("Question during plan review: %s", response[:100])
            self._answer_human_question(response)
            self.msg.send(
                f"Any more questions? Auto-proceeding in {int(deadline - time.time())}s, "
                "or reply **reject** to stop.",
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

    def _phase_dev_implement(self) -> None:
        self.state.phase = Phase.DEV_IMPLEMENT
        logger.info("Phase: DEV_IMPLEMENT")
        self.msg.send(
            "Starting implementation... You can ask me product questions anytime "
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
            result = run_claude(
                prompt=prompt,
                cwd=self.project_path,
                session_id=self.state.dev_session,
                allowed_tools=DEV_TOOLS,
                timeout=1800,
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

        self.msg.send("Implementation complete.", sender="Dev Agent")

    def _check_for_human_questions(self) -> None:
        """Check Mattermost for human messages and route them to the PM agent."""
        new = self.msg.bridge.read_new_human_messages()
        for msg in new:
            text = msg.get("message", "").strip()
            if not text:
                continue
            logger.info("Human question during impl: %s", text[:100])
            self._answer_human_question(text)

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
            timeout=1800,
        )
        self.state.pm_session = pm_result.get("session_id", self.state.pm_session)
        answer = pm_result.get("result", "I couldn't determine an answer from the PRD.")
        self.msg.send(answer, sender="PM Agent")

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
            timeout=1800,
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
            timeout=1800,
        )
        self.state.dev_session = result.get("session_id", self.state.dev_session)

    def _phase_create_pr(self) -> None:
        self.state.phase = Phase.CREATE_PR
        logger.info("Phase: CREATE_PR")
        self.msg.send("Creating pull request...", sender="Dev Agent")

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
            timeout=1800,
        )

        self.state.pr_url = result.get("result", "").strip()
        logger.info("PR URL: %s", self.state.pr_url)

    def _phase_done(self) -> None:
        self.state.phase = Phase.DONE
        logger.info("Phase: DONE")

        if self.state.pr_url:
            self.msg.send(f"PR created: {self.state.pr_url}", sender="Dev Agent")
        else:
            self.msg.send("Workflow complete (no PR URL captured).", sender="Orchestrator")

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

def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Team Orchestrator")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of Mattermost")
    parser.add_argument("--loop", action="store_true", help="Keep running for multiple features")
    parser.add_argument("--feature", type=str, default=None,
                        help="Skip PM agent and directly implement this feature description")
    args = parser.parse_args()

    config_path = args.config
    if not os.path.exists(config_path):
        # Try relative to script directory
        config_path = os.path.join(os.path.dirname(__file__), args.config)
    config = load_config(config_path)

    if args.dry_run:
        messenger = Messenger(bridge=None, dry_run=True)
    else:
        mm = config["mattermost"]
        bridge = MattermostBridge(
            ssh_host=config["openclaw"]["ssh_host"],
            channel_id=mm["channel_id"],
            mattermost_url=mm.get("url", "http://localhost:8065"),
            dev_bot_token=mm["dev_bot_token"],
            dev_bot_user_id=mm.get("dev_bot_user_id", ""),
            pm_bot_token=mm.get("pm_bot_token", ""),
            pm_bot_user_id=mm.get("pm_bot_user_id", ""),
            openclaw_account=config["openclaw"].get("openclaw_account"),
        )
        messenger = Messenger(bridge=bridge)

    loop = args.loop or config.get("workflow", {}).get("loop", False)
    orchestrator = Orchestrator(config, messenger)

    if args.feature:
        # Skip PM — inject the feature directly and jump to dev workflow
        orchestrator.state.feature = {
            "feature": args.feature[:60],
            "description": args.feature,
            "rationale": "Manually specified via --feature flag",
            "priority": "P1",
        }
        orchestrator.msg.send(
            f"Feature specified via CLI: **{args.feature[:60]}**",
            sender="Orchestrator",
        )
        orchestrator._phase_dev_specify()
        orchestrator._phase_dev_plan()
        orchestrator._phase_dev_tasks()
        if not orchestrator._phase_plan_review():
            return
        orchestrator._phase_dev_implement()
        orchestrator._phase_create_pr()
        orchestrator._phase_done()
    else:
        orchestrator.run(loop=loop)


if __name__ == "__main__":
    main()
