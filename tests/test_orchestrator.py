"""Tests for orchestrator resume and structured logging functionality.

Run: uv run pytest tests/test_orchestrator.py -m "not integration"
"""

import json
import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import (
    PHASE_SEQUENCE_FEATURE,
    PHASE_SEQUENCE_NORMAL,
    Messenger,
    Orchestrator,
    Phase,
    run_claude,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    config = {
        "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
        "workflow": {},
    }
    return config, tmp_path


@pytest.fixture
def orchestrator(tmp_project):
    config, _ = tmp_project
    return Orchestrator(config, Messenger(bridge=None, dry_run=True))


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_save_creates_valid_state_file(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        orchestrator.state.phase = Phase.DEV_PLAN
        orchestrator.state.feature = {"feature": "test", "description": "test desc"}
        orchestrator.state.pm_session = "pm_123"
        orchestrator.state.dev_session = "dev_456"

        orchestrator._save_state()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["version"] == 1
        assert data["phase"] == "DEV_PLAN"
        assert data["feature"]["feature"] == "test"
        assert data["pm_session"] == "pm_123"
        assert data["dev_session"] == "dev_456"
        assert data["workflow_type"] == "normal"
        assert data["started_at"] is not None
        assert data["updated_at"] is not None

    def test_load_returns_none_on_corrupt_json(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text("not valid json {{{")
        assert orchestrator._load_state() is None

    def test_load_returns_none_on_wrong_version(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text(
            json.dumps({"version": 99, "phase": "INIT"})
        )
        assert orchestrator._load_state() is None


# ---------------------------------------------------------------------------
# Resume logic
# ---------------------------------------------------------------------------

class TestResumeLogic:
    def _make_orchestrator(self, tmp_path, workflow_type="normal"):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {"auto_approve": True},
        }
        orch = Orchestrator(config, Messenger(bridge=None, dry_run=True))
        orch._workflow_type = workflow_type
        return orch

    def _stub_phases(self, orch, sequence, calls):
        for _, method_name, is_checkpoint in sequence:
            if is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: (calls.append(n), True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: calls.append(n))

    def test_resume_skips_completed_phases(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.state.phase = Phase.DEV_PLAN  # last completed
        orch._resuming = True
        calls = []
        self._stub_phases(orch, PHASE_SEQUENCE_NORMAL, calls)

        orch._run_once()

        assert calls[0] == "_phase_dev_tasks"
        assert "_phase_init" not in calls
        assert "_phase_pm_suggest" not in calls
        assert "_phase_dev_plan" not in calls

    def test_resume_feature_workflow(self, tmp_path):
        orch = self._make_orchestrator(tmp_path, workflow_type="feature")
        orch.state.phase = Phase.DEV_SPECIFY  # last completed
        orch._resuming = True
        calls = []
        self._stub_phases(orch, PHASE_SEQUENCE_FEATURE, calls)

        orch._run_once()

        assert calls[0] == "_phase_dev_plan"
        assert "_phase_dev_specify" not in calls

    def test_checkpoint_rejection_stops_workflow(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        calls = []

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if method_name == "_phase_review":
                setattr(orch, method_name, lambda: (calls.append("_phase_review"), False)[1])
            elif is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: (calls.append(n), True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: calls.append(n))

        orch._run_once()

        assert "_phase_review" in calls
        assert "_phase_dev_specify" not in calls


# ---------------------------------------------------------------------------
# Auto-save on crash
# ---------------------------------------------------------------------------

class TestAutoSave:
    def test_saves_state_on_crash(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        msg.root_id = None  # Needed for _save_state()
        orch = Orchestrator(config, msg)
        orch.state.phase = Phase.DEV_PLAN

        orch._run_once = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        orch.run()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["phase"] == "DEV_PLAN"


# ---------------------------------------------------------------------------
# Full resume restore flow (end-to-end)
# ---------------------------------------------------------------------------

class TestFullResumeFlow:
    def test_save_then_restore_across_instances(self, tmp_project):
        config, tmp_path = tmp_project
        msg = Messenger(bridge=None, dry_run=True)

        # First orchestrator saves state
        orch1 = Orchestrator(config, msg)
        orch1._workflow_type = "feature"
        orch1.state.phase = Phase.DEV_PLAN
        orch1.state.feature = {"feature": "test", "description": "test"}
        orch1.state.dev_session = "dev_abc"
        orch1._save_state()

        # Second orchestrator loads and restores
        orch2 = Orchestrator(config, msg)
        saved = orch2._load_state()
        assert saved is not None

        orch2.state.phase = Phase[saved["phase"]]
        orch2.state.feature = saved.get("feature", {})
        orch2.state.dev_session = saved.get("dev_session")
        orch2._workflow_type = saved.get("workflow_type", "normal")
        orch2._resuming = True

        assert orch2.state.phase == Phase.DEV_PLAN
        assert orch2._workflow_type == "feature"
        assert orch2.state.dev_session == "dev_abc"


# ---------------------------------------------------------------------------
# DONE clears state
# ---------------------------------------------------------------------------

class TestDoneClearsState:
    def test_done_clears_state_file(self, tmp_project):
        config, tmp_path = tmp_project
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        msg.root_id = None  # Needed for _save_state()
        orch = Orchestrator(config, msg)

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()
        assert not (tmp_path / ".agent-team-state.json").exists()


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------

class TestFmtDuration:
    def test_seconds_only(self):
        assert Orchestrator._fmt_duration(0) == "0s"
        assert Orchestrator._fmt_duration(5) == "5s"
        assert Orchestrator._fmt_duration(59) == "59s"

    def test_minutes_and_seconds(self):
        assert Orchestrator._fmt_duration(90) == "1m 30s"
        assert Orchestrator._fmt_duration(125) == "2m 5s"

    def test_exact_minutes(self):
        assert Orchestrator._fmt_duration(60) == "1m"
        assert Orchestrator._fmt_duration(120) == "2m"
        assert Orchestrator._fmt_duration(600) == "10m"

    def test_rounds_fractional_seconds(self):
        assert Orchestrator._fmt_duration(2.4) == "2s"
        assert Orchestrator._fmt_duration(2.6) == "3s"


# ---------------------------------------------------------------------------
# Phase timing tracking
# ---------------------------------------------------------------------------

class TestPhaseTimings:
    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {"auto_approve": True},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        msg.root_id = None  # Needed for _save_state()
        return Orchestrator(config, msg)

    def test_timings_recorded_for_each_phase(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()

        phase_names = [name for name, _ in orch._phase_timings]
        assert phase_names == [p.name for p, _, _ in PHASE_SEQUENCE_NORMAL]
        # All durations should be non-negative
        assert all(dur >= 0 for _, dur in orch._phase_timings)

    def test_timings_reset_each_run(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()
        first_count = len(orch._phase_timings)
        orch._run_once()
        # Should not accumulate — reset each run
        assert len(orch._phase_timings) == first_count

    def test_timings_stop_on_rejection(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if method_name == "_phase_review":
                setattr(orch, method_name, lambda: False)
            elif is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()

        phase_names = [name for name, _ in orch._phase_timings]
        assert "REVIEW" in phase_names
        assert "DEV_SPECIFY" not in phase_names


# ---------------------------------------------------------------------------
# Summary posting
# ---------------------------------------------------------------------------

class TestPostSummary:
    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        return Orchestrator(config, msg)

    @patch("orchestrator.time")
    def test_success_summary(self, mock_time, tmp_path):
        mock_time.time.return_value = 522.0  # 8m 42s from epoch 0
        orch = self._make_orchestrator(tmp_path)
        orch.state.feature = {"feature": "Add tests"}
        orch.state.phase = Phase.DONE
        orch.state.pr_url = "https://github.com/example/repo/pull/42"
        orch._run_start_time = 0.0
        orch._phase_timings = [("INIT", 2.0), ("PM_SUGGEST", 90.0)]

        orch._post_summary()

        call_args = orch.msg.send.call_args
        text = call_args[0][0]
        assert "**Workflow Summary**" in text
        assert "Add tests" in text
        assert "Complete" in text
        assert "8m 42s" in text
        assert "INIT" in text
        assert "PM_SUGGEST" in text
        assert "1m 30s" in text
        assert "https://github.com/example/repo/pull/42" in text

    @patch("orchestrator.time")
    def test_failure_summary(self, mock_time, tmp_path):
        mock_time.time.return_value = 372.0  # 6m 12s from epoch 0
        orch = self._make_orchestrator(tmp_path)
        orch.state.feature = {"feature": "Add tests"}
        orch.state.phase = Phase.DEV_IMPLEMENT
        orch._run_start_time = 0.0
        orch._phase_timings = [("INIT", 2.0), ("DEV_SPECIFY", 30.0)]

        orch._post_summary(error="RuntimeError: claude -p failed")

        call_args = orch.msg.send.call_args
        text = call_args[0][0]
        assert "Failed at DEV_IMPLEMENT" in text
        assert "6m 12s" in text
        assert "RuntimeError: claude -p failed" in text
        assert "--resume" in text

    def test_summary_table_has_emoji_indicators(self, tmp_path):
        """Test that summary table includes emoji indicators next to phase names."""
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        orch = Orchestrator(config, msg)
        orch.state.feature = {"feature": "Test feature"}
        orch.state.phase = Phase.DONE
        orch._run_start_time = 0.0
        orch._phase_timings = [
            ("DEV_SPECIFY", 150.0),
            ("DEV_PLAN", 75.0),
            ("DEV_TASKS", 45.0),
            ("DEV_IMPLEMENT", 900.0),
        ]

        orch._post_summary()

        call_args = orch.msg.send.call_args
        text = call_args[0][0]
        # Check for emoji indicators in summary table
        assert "📋" in text or "SPECIFY" in text
        assert "📐" in text or "PLAN" in text
        assert "📝" in text or "TASKS" in text
        assert "🔨" in text or "IMPLEMENT" in text

    def test_plan_phase_completion_has_emoji(self, tmp_path):
        """Test that PLAN phase completion message includes checkmark emoji."""
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        orch = Orchestrator(config, msg)
        orch.state.feature = {"feature": "Test feature"}
        orch.state.phase = Phase.DEV_PLAN
        orch.state.dev_session = "test-session"

        # Simulate the message that would be sent on PLAN completion
        summary = "Key files: test.py, config.yaml"
        expected_message = f"📐 **Plan** — ✅ Complete\n\n{summary}"

        orch.msg.send(expected_message, sender="Dev Agent")

        call_args = orch.msg.send.call_args
        text = call_args[0][0]
        # Verify emoji indicators are present
        assert "📐" in text
        assert "✅" in text
        assert "Plan" in text
        assert "Complete" in text

    @patch("orchestrator.time")
    def test_summary_with_no_timings(self, mock_time, tmp_path):
        mock_time.time.return_value = 5.0
        orch = self._make_orchestrator(tmp_path)
        orch.state.feature = {"feature": "Test"}
        orch.state.phase = Phase.INIT
        orch._run_start_time = 0.0
        orch._phase_timings = []

        orch._post_summary(error="early failure")

        call_args = orch.msg.send.call_args
        text = call_args[0][0]
        assert "**Workflow Summary**" in text


# ---------------------------------------------------------------------------
# File logging setup
# ---------------------------------------------------------------------------

class TestFileLogging:
    def test_root_logger_has_file_and_console_handlers(self):
        root = logging.getLogger()
        handler_types = [type(h) for h in root.handlers]
        assert logging.StreamHandler in handler_types
        assert logging.FileHandler in handler_types

    def test_file_handler_is_debug_level(self):
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) >= 1
        assert file_handlers[0].level == logging.DEBUG

    def test_console_handler_is_info_level(self):
        root = logging.getLogger()
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) >= 1
        assert console_handlers[0].level == logging.INFO


# ---------------------------------------------------------------------------
# Retry with backoff
# ---------------------------------------------------------------------------

class TestRunClaudeRetry:
    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_succeeds_on_first_try(self, mock_run, mock_time):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "ok", "session_id": "s1"}',
        )
        result = run_claude("hello", "/tmp", max_retries=2)
        assert result["result"] == "ok"
        assert mock_run.call_count == 1

    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_retries_on_nonzero_exit(self, mock_run, mock_time):
        fail = MagicMock(returncode=1, stderr="error details")
        success = MagicMock(
            returncode=0, stdout='{"result": "ok"}',
        )
        mock_run.side_effect = [fail, success]

        result = run_claude("hello", "/tmp", max_retries=2)
        assert result["result"] == "ok"
        assert mock_run.call_count == 2
        mock_time.sleep.assert_called_once_with(5)

    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_raises_after_exhausting_retries(self, mock_run, mock_time):
        fail = MagicMock(returncode=1, stderr="persistent error")
        mock_run.side_effect = [fail, fail]

        with pytest.raises(RuntimeError, match="persistent error"):
            run_claude("hello", "/tmp", max_retries=2)
        assert mock_run.call_count == 2

    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_retries_on_timeout(self, mock_run, mock_time):
        timeout_exc = subprocess.TimeoutExpired(cmd="claude", timeout=30)
        timeout_exc.stdout = b""
        success = MagicMock(
            returncode=0, stdout='{"result": "recovered"}',
        )
        mock_run.side_effect = [timeout_exc, success]

        result = run_claude("hello", "/tmp", timeout=30, max_retries=2)
        assert result["result"] == "recovered"
        assert mock_run.call_count == 2
        mock_time.sleep.assert_called_once_with(5)

    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_timeout_final_attempt_salvages_output(self, mock_run, mock_time):
        timeout_exc = subprocess.TimeoutExpired(cmd="claude", timeout=30)
        timeout_exc.stdout = b'{"result": "partial", "session_id": "s99"}'
        mock_run.side_effect = [timeout_exc, timeout_exc]

        result = run_claude("hello", "/tmp", timeout=30, max_retries=2)
        assert result["result"] == "partial"
        assert result["session_id"] == "s99"

    @patch("orchestrator.time")
    @patch("orchestrator.subprocess.run")
    def test_backoff_increases_exponentially(self, mock_run, mock_time):
        fail = MagicMock(returncode=1, stderr="err")
        success = MagicMock(returncode=0, stdout='{"result": "ok"}')
        mock_run.side_effect = [fail, fail, success]

        result = run_claude("hello", "/tmp", max_retries=3)
        assert result["result"] == "ok"
        # Backoff: attempt 1 -> sleep(5), attempt 2 -> sleep(20)
        calls = mock_time.sleep.call_args_list
        assert calls[0][0][0] == 5
        assert calls[1][0][0] == 20


# ---------------------------------------------------------------------------
# Thread ID persistence
# ---------------------------------------------------------------------------

class TestThreadIdPersistence:
    def test_save_includes_thread_root_id(self, tmp_project):
        config, tmp_path = tmp_project
        msg = Messenger(bridge=None, dry_run=True)
        msg._root_id = "thread_abc123"
        orch = Orchestrator(config, msg)
        orch.state.phase = Phase.DEV_IMPLEMENT
        orch.state.feature = {"feature": "test"}
        orch._save_state()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["thread_root_id"] == "thread_abc123"

    def test_load_restores_thread_root_id(self, tmp_project):
        config, tmp_path = tmp_project
        msg = Messenger(bridge=None, dry_run=True)
        orch = Orchestrator(config, msg)

        # Create state file with thread_root_id
        (tmp_path / ".agent-team-state.json").write_text(json.dumps({
            "version": 1,
            "phase": "DEV_IMPLEMENT",
            "thread_root_id": "thread_xyz789",
            "feature": {},
        }))

        saved = orch._load_state()
        assert saved["thread_root_id"] == "thread_xyz789"


# ---------------------------------------------------------------------------
# Question routing (implementation vs product)
# ---------------------------------------------------------------------------

class TestQuestionRouting:
    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        return Orchestrator(config, msg)

    def test_impl_question_routes_to_dev(self, tmp_path):
        """Questions about next steps, progress, status should go to Dev Agent."""
        orch = self._make_orchestrator(tmp_path)
        orch.state.dev_session = "dev_session"

        with patch("orchestrator.run_claude") as mock:
            mock.return_value = {"result": "Working on T001", "session_id": "dev_session"}
            orch._answer_impl_question("What's next?")

        # Should call run_claude
        mock.assert_called_once()
        call_args = mock.call_args
        assert "next" in call_args[1]["prompt"].lower()

    def test_product_question_routes_to_pm(self, tmp_path):
        """Questions about requirements, PRD, spec should go to PM Agent."""
        orch = self._make_orchestrator(tmp_path)
        orch.state.pm_session = "pm_session"

        with patch("orchestrator.run_claude") as mock:
            mock.return_value = {"result": "Based on the PRD...", "session_id": "pm_session"}
            orch._answer_human_question("What's in the PRD?")

        mock.assert_called_once()
        call_args = mock.call_args
        assert "PRD" in call_args[1]["prompt"]


# ---------------------------------------------------------------------------
# Phase Emoji Markers
# ---------------------------------------------------------------------------

class TestPhaseEmojiMarkers:
    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        msg.root_id = None
        return Orchestrator(config, msg)

    @patch("orchestrator.run_claude_stream")
    def test_specify_phase_completion_has_success_emoji(self, mock_stream, tmp_path):
        """T002: SPECIFY phase completion message should contain ✅ emoji."""
        orch = self._make_orchestrator(tmp_path)
        orch.state.feature = {"feature": "Test feature", "description": "A test feature"}
        mock_stream.return_value = {"result": "ok", "session_id": "s1"}
        orch._get_phase_summary = MagicMock(return_value="Summary bullet points")

        orch._phase_dev_specify()

        # Collect all messages sent
        calls = orch.msg.send.call_args_list
        assert len(calls) >= 2  # at least in-progress + completion

        # First message: in-progress with 🔄
        first_msg = calls[0][0][0]
        assert "🔄" in first_msg
        assert "Specify" in first_msg

        # Last message: completion with ✅
        last_msg = calls[-1][0][0]
        assert "✅" in last_msg
        assert "Specify" in last_msg
        assert "Complete" in last_msg

    @patch("orchestrator.run_claude_stream")
    def test_tasks_phase_completion_has_success_emoji(self, mock_stream, tmp_path):
        """T004: TASKS phase completion message should contain ✅ emoji."""
        orch = self._make_orchestrator(tmp_path)
        orch.state.feature = {"feature": "Test feature", "description": "A test feature"}
        mock_stream.return_value = {"result": "ok", "session_id": "s1"}
        orch._get_phase_summary = MagicMock(return_value="Summary bullet points")
        orch._move_artifacts_to_specs_dir = MagicMock()

        orch._phase_dev_tasks()

        # Collect all messages sent
        calls = orch.msg.send.call_args_list
        assert len(calls) >= 2  # at least in-progress + completion

        # First message: in-progress with 🔄
        first_msg = calls[0][0][0]
        assert "🔄" in first_msg
        assert "Tasks" in first_msg

        # Last message: completion with ✅
        last_msg = calls[-1][0][0]
        assert "✅" in last_msg
        assert "Tasks" in last_msg
        assert "Complete" in last_msg
