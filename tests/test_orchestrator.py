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

    def test_recovery_from_backup_on_corrupt_json(self, orchestrator, tmp_project):
        """When current state has corrupt JSON, recover from backup."""
        _, tmp_path = tmp_project
        # Create valid backup
        valid_state = {
            "version": 1,
            "workflow_type": "normal",
            "phase": "DEV_PLAN",
            "feature": {"feature": "test"},
            "pm_session": None,
            "dev_session": None,
            "pr_url": None,
            "branch_name": "test-branch",
            "worker_handoff": False,
            "original_path": str(tmp_path),
            "worktree_path": None,
            "thread_root_id": None,
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        (tmp_path / ".agent-team-state.json.bak").write_text(json.dumps(valid_state))
        # Corrupt current state
        (tmp_path / ".agent-team-state.json").write_text("not valid json {{{")

        result = orchestrator._load_state()

        assert result is not None
        assert result["phase"] == "DEV_PLAN"
        assert result["branch_name"] == "test-branch"

    def test_recovery_from_backup_on_missing_fields(self, orchestrator, tmp_project):
        """When current state has missing required fields, recover from backup."""
        _, tmp_path = tmp_project
        # Create valid backup
        valid_state = {
            "version": 1,
            "workflow_type": "normal",
            "phase": "DEV_IMPLEMENT",
            "feature": {"feature": "test"},
            "pm_session": None,
            "dev_session": None,
            "pr_url": None,
            "branch_name": "test-branch",
            "worker_handoff": False,
            "original_path": str(tmp_path),
            "worktree_path": None,
            "thread_root_id": None,
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        (tmp_path / ".agent-team-state.json.bak").write_text(json.dumps(valid_state))
        # Create state with missing required fields
        (tmp_path / ".agent-team-state.json").write_text(json.dumps({"phase": "INIT"}))

        result = orchestrator._load_state()

        assert result is not None
        assert result["phase"] == "DEV_IMPLEMENT"

    def test_returns_none_when_both_state_and_backup_corrupt(self, orchestrator, tmp_project):
        """When both state and backup are corrupt, return None."""
        _, tmp_path = tmp_project
        # Corrupt backup
        (tmp_path / ".agent-team-state.json.bak").write_text("not valid json {{{")
        # Corrupt current state
        (tmp_path / ".agent-team-state.json").write_text("also corrupt {{{")

        result = orchestrator._load_state()

        assert result is None

    def test_load_backup_returns_none_when_no_backup(self, orchestrator, tmp_project):
        """When no backup exists, _load_backup returns None."""
        _, tmp_path = tmp_project

        result = orchestrator._load_backup()

        assert result is None

    def test_error_message_on_corrupt_json(self, orchestrator, tmp_project, caplog):
        """Verify error message logged for corrupt JSON."""
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text("not valid json {{{")

        with caplog.at_level(logging.WARNING):
            orchestrator._load_state()

        assert any("corrupted (invalid JSON)" in msg for msg in caplog.messages)

    def test_error_message_on_missing_fields(self, orchestrator, tmp_project, caplog):
        """Verify error message logged for missing required fields."""
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text(json.dumps({"phase": "INIT"}))

        with caplog.at_level(logging.WARNING):
            orchestrator._load_state()

        assert any("corrupted (missing required fields)" in msg for msg in caplog.messages)

    def test_error_message_when_both_corrupt(self, orchestrator, tmp_project, caplog):
        """Verify error message logged when both state and backup are corrupt."""
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json.bak").write_text("corrupt")
        (tmp_path / ".agent-team-state.json").write_text("corrupt")

        with caplog.at_level(logging.WARNING):
            orchestrator._load_state()

        assert any("Both state file and backup are corrupted" in msg for msg in caplog.messages)

    def test_info_message_when_no_state(self, orchestrator, tmp_project, caplog):
        """Verify info message logged when no saved state exists."""
        _, tmp_path = tmp_project
        # Ensure no state file exists

        with caplog.at_level(logging.INFO):
            orchestrator._load_state()

        assert any("No saved state found" in msg for msg in caplog.messages)

    def test_recovery_success_logged(self, orchestrator, tmp_project, caplog):
        """Verify recovery from backup logs success message."""
        _, tmp_path = tmp_project
        # Create valid backup
        valid_state = {
            "version": 1,
            "workflow_type": "normal",
            "phase": "DEV_PLAN",
            "feature": {"feature": "test"},
            "pm_session": None,
            "dev_session": None,
            "pr_url": None,
            "branch_name": "test-branch",
            "worker_handoff": False,
            "original_path": str(tmp_path),
            "worktree_path": None,
            "thread_root_id": None,
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        (tmp_path / ".agent-team-state.json.bak").write_text(json.dumps(valid_state))
        # Corrupt current state
        (tmp_path / ".agent-team-state.json").write_text("corrupt")

        with caplog.at_level(logging.INFO):
            result = orchestrator._load_state()

        assert result is not None
        assert any("Recovered state from backup" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Backup creation tests
# ---------------------------------------------------------------------------

class TestBackupCreation:
    """Tests for backup creation functionality (T020)."""

    def test_backup_file_path_returns_correct_path(self, orchestrator, tmp_project):
        """Verify _backup_file_path returns correct backup path."""
        _, tmp_path = tmp_project

        backup_path = orchestrator._backup_file_path()

        assert backup_path == tmp_path / ".agent-team-state.json.bak"

    def test_create_backup_returns_true_when_no_state(self, orchestrator, tmp_project):
        """Verify _create_backup returns True when no state file exists."""
        _, tmp_path = tmp_project
        # Ensure no state file exists
        assert not (tmp_path / ".agent-team-state.json").exists()

        result = orchestrator._create_backup()

        assert result is True
        assert not (tmp_path / ".agent-team-state.json.bak").exists()

    def test_create_backup_copies_state_file(self, orchestrator, tmp_project):
        """Verify _create_backup copies state file to backup."""
        _, tmp_path = tmp_project
        # Create a state file first
        state_data = {"version": 1, "phase": "INIT", "workflow_type": "normal"}
        (tmp_path / ".agent-team-state.json").write_text(json.dumps(state_data))

        result = orchestrator._create_backup()

        assert result is True
        assert (tmp_path / ".agent-team-state.json.bak").exists()
        backup_content = json.loads((tmp_path / ".agent-team-state.json.bak").read_text())
        assert backup_content["phase"] == "INIT"
        assert backup_content["version"] == 1

    def test_backup_replaces_old_backup(self, orchestrator, tmp_project):
        """Verify backup replaces old backup with new content."""
        _, tmp_path = tmp_project
        # Create initial state
        old_state = {"version": 1, "phase": "INIT", "workflow_type": "normal"}
        (tmp_path / ".agent-team-state.json").write_text(json.dumps(old_state))
        # Create old backup
        (tmp_path / ".agent-team-state.json.bak").write_text(json.dumps({"version": 1, "phase": "OLD"}))

        # Save new state with different phase
        orchestrator.state.phase = Phase.DEV_PLAN
        orchestrator.state.feature = {"feature": "test"}
        orchestrator._save_state()

        # Backup should now have the old state content
        backup_content = json.loads((tmp_path / ".agent-team-state.json.bak").read_text())
        assert backup_content["phase"] == "INIT"  # Old state was backed up

    def test_save_state_creates_backup_before_writing(self, orchestrator, tmp_project, caplog):
        """Verify _save_state creates backup before writing new state."""
        _, tmp_path = tmp_project
        # Create existing state
        old_state = {"version": 1, "phase": "INIT", "workflow_type": "normal"}
        (tmp_path / ".agent-team-state.json").write_text(json.dumps(old_state))

        # Set new state
        orchestrator.state.phase = Phase.DEV_PLAN
        orchestrator.state.feature = {"feature": "test"}
        orchestrator._save_state()

        # Verify backup was created with old state
        assert (tmp_path / ".agent-team-state.json.bak").exists()
        backup_content = json.loads((tmp_path / ".agent-team-state.json.bak").read_text())
        assert backup_content["phase"] == "INIT"

        # Verify new state was written
        new_state = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert new_state["phase"] == "DEV_PLAN"

    def test_create_backup_preserves_file_metadata(self, orchestrator, tmp_project):
        """Verify backup preserves file metadata (timestamps)."""
        _, tmp_path = tmp_project
        # Create state file
        (tmp_path / ".agent-team-state.json").write_text(json.dumps({"version": 1, "phase": "INIT"}))

        import time
        time.sleep(0.01)  # Small delay to ensure different timestamps

        orchestrator._create_backup()

        state_stat = (tmp_path / ".agent-team-state.json").stat()
        backup_stat = (tmp_path / ".agent-team-state.json.bak").stat()

        # copy2 should preserve timestamps (allowing small variance for filesystem precision)
        assert abs(state_stat.st_mtime - backup_stat.st_mtime) < 0.1


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

        # Create state file with thread_root_id (including all required fields)
        (tmp_path / ".agent-team-state.json").write_text(json.dumps({
            "version": 1,
            "workflow_type": "normal",
            "phase": "DEV_IMPLEMENT",
            "feature": {},
            "pm_session": None,
            "dev_session": None,
            "pr_url": None,
            "branch_name": "test-branch",
            "worker_handoff": False,
            "original_path": str(tmp_path),
            "worktree_path": None,
            "thread_root_id": "thread_xyz789",
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
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
# State validation (unit tests for _validate_state)
# ---------------------------------------------------------------------------

class TestValidateState:
    """Unit tests for the _validate_state method."""

    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        return Orchestrator(config, msg)

    def _valid_state(self, **overrides):
        """Create a valid state dict with optional overrides."""
        state = {
            "version": 1,
            "workflow_type": "normal",
            "phase": "INIT",
            "feature": None,
            "pm_session": None,
            "dev_session": None,
            "pr_url": None,
            "branch_name": None,
            "worker_handoff": False,
            "original_path": "/tmp/test",
            "worktree_path": None,
            "thread_root_id": None,
            "started_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        state.update(overrides)
        return state

    def test_valid_state_passes_validation(self, tmp_path):
        """Valid state returns (True, None)."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state()

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is True
        assert error_msg is None

    def test_valid_state_with_all_fields_passes(self, tmp_path):
        """State with all fields populated passes validation."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(
            phase="DEV_IMPLEMENT",
            feature={"feature": "Test feature", "description": "Test desc"},
            pm_session="pm_123",
            dev_session="dev_456",
            pr_url="https://github.com/org/repo/pull/1",
            branch_name="feature/test",
            worker_handoff=True,
            worktree_path="/tmp/worktree",
            thread_root_id="thread_abc",
        )

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is True
        assert error_msg is None

    def test_missing_required_field_fails_validation(self, tmp_path):
        """Missing required field returns (False, error_message)."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state()
        del state["version"]

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Missing required fields" in error_msg
        assert "version" in error_msg

    def test_missing_multiple_fields_fails_validation(self, tmp_path):
        """Missing multiple required fields returns error listing all."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state()
        del state["phase"]
        del state["workflow_type"]
        del state["branch_name"]

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "phase" in error_msg
        assert "workflow_type" in error_msg
        assert "branch_name" in error_msg

    def test_invalid_version_fails_validation(self, tmp_path):
        """Invalid version returns (False, error_message)."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(version=99)

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid version" in error_msg
        assert "99" in error_msg

    def test_version_zero_fails_validation(self, tmp_path):
        """Version 0 (not 1) fails validation."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(version=0)

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid version" in error_msg

    def test_invalid_phase_fails_validation(self, tmp_path):
        """Invalid phase returns (False, error_message)."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(phase="INVALID_PHASE")

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid phase" in error_msg
        assert "INVALID_PHASE" in error_msg

    def test_invalid_field_type_fails_validation(self, tmp_path):
        """Invalid field type returns (False, error_message).

        Note: phase validation runs before type check, so phase=123 fails with
        'Invalid phase' rather than 'Invalid type for phase'.
        """
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(phase=123)  # Should be str

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        # Phase check happens before type check
        assert "Invalid phase" in error_msg

    def test_string_field_as_int_fails_validation(self, tmp_path):
        """String field with int value fails type validation."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(workflow_type=123)

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid type for workflow_type" in error_msg

    def test_bool_field_as_string_fails_validation(self, tmp_path):
        """Bool field with string value fails type validation."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(worker_handoff="true")  # Should be bool

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid type for worker_handoff" in error_msg

    def test_int_field_as_string_fails_validation(self, tmp_path):
        """Int field with string value fails type validation.

        Note: version check runs before type check, so version="1" fails with
        'Invalid version' rather than 'Invalid type for version'.
        """
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(version="1")  # Should be int

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        # Version check happens before type check
        assert "Invalid version" in error_msg

    def test_null_field_with_string_value_fails_validation(self, tmp_path):
        """Field that allows None but gets wrong type fails."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(feature="not_a_dict")  # Should be dict or None

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is False
        assert "Invalid type for feature" in error_msg

    def test_empty_dict_passes_for_optional_dict_field(self, tmp_path):
        """Empty dict {} is valid for feature field."""
        orch = self._make_orchestrator(tmp_path)
        state = self._valid_state(feature={})

        is_valid, error_msg = orch._validate_state(state)

        assert is_valid is True
        assert error_msg is None

    def test_all_phases_are_valid(self, tmp_path):
        """All valid Phase enum values pass validation."""
        orch = self._make_orchestrator(tmp_path)

        from orchestrator import Phase
        for phase in Phase:
            state = self._valid_state(phase=phase.name)
            is_valid, error_msg = orch._validate_state(state)
            assert is_valid is True, f"Phase {phase.name} should be valid: {error_msg}"

