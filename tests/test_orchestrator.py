"""Tests for orchestrator resume functionality.

Run: uv run pytest tests/test_orchestrator.py -m "not integration"
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import (
    PHASE_SEQUENCE_FEATURE,
    PHASE_SEQUENCE_NORMAL,
    Messenger,
    Orchestrator,
    Phase,
    WorkflowState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = {
    "project": {"path": "/tmp/test-project", "prd_path": "docs/PRD.md"},
    "workflow": {},
}


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory and return config pointing to it."""
    config = {
        "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
        "workflow": {},
    }
    return config, tmp_path


@pytest.fixture
def orchestrator(tmp_project):
    config, tmp_path = tmp_project
    msg = Messenger(bridge=None, dry_run=True)
    return Orchestrator(config, msg)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestSaveState:
    def test_creates_state_file(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        orchestrator.state.phase = Phase.DEV_PLAN
        orchestrator.state.feature = {"feature": "test", "description": "test desc"}
        orchestrator.state.pm_session = "pm_123"
        orchestrator.state.dev_session = "dev_456"

        orchestrator._save_state()

        state_file = tmp_path / ".agent-team-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["version"] == 1
        assert data["phase"] == "DEV_PLAN"
        assert data["feature"]["feature"] == "test"
        assert data["pm_session"] == "pm_123"
        assert data["dev_session"] == "dev_456"
        assert data["workflow_type"] == "normal"
        assert "started_at" in data
        assert "updated_at" in data

    def test_preserves_started_at(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        orchestrator._started_at = "2026-01-01T00:00:00+00:00"
        orchestrator.state.phase = Phase.DEV_PLAN

        orchestrator._save_state()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["started_at"] == "2026-01-01T00:00:00+00:00"

    def test_sets_started_at_on_first_save(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        assert orchestrator._started_at is None

        orchestrator._save_state()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["started_at"] is not None
        assert orchestrator._started_at is not None

    def test_saves_feature_workflow_type(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        orchestrator._workflow_type = "feature"

        orchestrator._save_state()

        data = json.loads((tmp_path / ".agent-team-state.json").read_text())
        assert data["workflow_type"] == "feature"


class TestLoadState:
    def test_returns_none_when_missing(self, orchestrator):
        assert orchestrator._load_state() is None

    def test_loads_valid_state(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        state_data = {
            "version": 1,
            "workflow_type": "feature",
            "phase": "DEV_TASKS",
            "feature": {"feature": "auth", "description": "Add authentication"},
            "pm_session": "pm_abc",
            "dev_session": "dev_xyz",
            "pr_url": None,
            "started_at": "2026-02-16T10:00:00+00:00",
            "updated_at": "2026-02-16T10:05:00+00:00",
        }
        (tmp_path / ".agent-team-state.json").write_text(json.dumps(state_data))

        loaded = orchestrator._load_state()
        assert loaded is not None
        assert loaded["phase"] == "DEV_TASKS"
        assert loaded["workflow_type"] == "feature"
        assert loaded["dev_session"] == "dev_xyz"

    def test_returns_none_on_corrupt_json(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text("not valid json {{{")

        assert orchestrator._load_state() is None

    def test_returns_none_on_wrong_version(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        (tmp_path / ".agent-team-state.json").write_text(
            json.dumps({"version": 99, "phase": "INIT"})
        )

        assert orchestrator._load_state() is None


class TestClearState:
    def test_deletes_state_file(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        state_file = tmp_path / ".agent-team-state.json"
        state_file.write_text("{}")

        orchestrator._clear_state()

        assert not state_file.exists()

    def test_no_error_when_missing(self, orchestrator):
        # Should not raise
        orchestrator._clear_state()


# ---------------------------------------------------------------------------
# Phase sequences
# ---------------------------------------------------------------------------

class TestPhaseSequences:
    def test_normal_sequence_has_all_phases(self):
        phases = [p for p, _, _ in PHASE_SEQUENCE_NORMAL]
        assert phases == [
            Phase.INIT, Phase.PM_SUGGEST, Phase.REVIEW,
            Phase.DEV_SPECIFY, Phase.DEV_PLAN, Phase.DEV_TASKS,
            Phase.PLAN_REVIEW, Phase.DEV_IMPLEMENT, Phase.CREATE_PR, Phase.DONE,
        ]

    def test_feature_sequence_skips_pm_phases(self):
        phases = [p for p, _, _ in PHASE_SEQUENCE_FEATURE]
        assert Phase.INIT not in phases
        assert Phase.PM_SUGGEST not in phases
        assert Phase.REVIEW not in phases
        assert phases[0] == Phase.DEV_SPECIFY

    def test_checkpoints_are_review_and_plan_review(self):
        checkpoints_normal = [(p, m) for p, m, c in PHASE_SEQUENCE_NORMAL if c]
        assert len(checkpoints_normal) == 2
        assert checkpoints_normal[0][0] == Phase.REVIEW
        assert checkpoints_normal[1][0] == Phase.PLAN_REVIEW

        checkpoints_feature = [(p, m) for p, m, c in PHASE_SEQUENCE_FEATURE if c]
        assert len(checkpoints_feature) == 1
        assert checkpoints_feature[0][0] == Phase.PLAN_REVIEW


# ---------------------------------------------------------------------------
# _run_once resume logic
# ---------------------------------------------------------------------------

class TestRunOnceResume:
    """Test that _run_once skips completed phases on resume."""

    def _make_orchestrator(self, tmp_path, workflow_type="normal"):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {"auto_approve": True},
        }
        msg = Messenger(bridge=None, dry_run=True)
        orch = Orchestrator(config, msg)
        orch._workflow_type = workflow_type
        return orch

    def test_fresh_run_starts_from_beginning(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        calls = []

        # Patch all phase methods to just record they were called
        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: (calls.append(n), True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: calls.append(n))

        orch._run_once()

        assert len(calls) == len(PHASE_SEQUENCE_NORMAL)
        assert calls[0] == "_phase_init"
        assert calls[-1] == "_phase_done"

    def test_resume_skips_completed_phases(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.state.phase = Phase.DEV_PLAN  # last completed phase
        orch._resuming = True
        calls = []

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: (calls.append(n), True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: calls.append(n))

        orch._run_once()

        # Should start from DEV_TASKS (index 5), skipping INIT through DEV_PLAN
        assert calls[0] == "_phase_dev_tasks"
        assert "_phase_init" not in calls
        assert "_phase_pm_suggest" not in calls
        assert "_phase_dev_plan" not in calls

    def test_resume_feature_workflow(self, tmp_path):
        orch = self._make_orchestrator(tmp_path, workflow_type="feature")
        orch.state.phase = Phase.DEV_SPECIFY  # last completed phase
        orch._resuming = True
        calls = []

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_FEATURE:
            if is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: (calls.append(n), True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: calls.append(n))

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

        # Should stop at REVIEW (rejected)
        assert "_phase_review" in calls
        assert "_phase_dev_specify" not in calls

    def test_resuming_flag_cleared_after_run(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._resuming = True
        orch.state.phase = Phase.CREATE_PR

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda n=method_name: ([], True)[1])
            else:
                setattr(orch, method_name, lambda n=method_name: None)

        orch._run_once()
        assert orch._resuming is False


# ---------------------------------------------------------------------------
# run() auto-save on error
# ---------------------------------------------------------------------------

class TestRunAutoSave:
    def _make_orchestrator(self, tmp_path):
        config = {
            "project": {"path": str(tmp_path), "prd_path": "docs/PRD.md"},
            "workflow": {},
        }
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        orch = Orchestrator(config, msg)
        return orch

    def test_saves_state_on_exception(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.state.phase = Phase.DEV_PLAN

        def exploding_run_once():
            raise RuntimeError("boom")

        orch._run_once = exploding_run_once
        orch.run()

        state_file = tmp_path / ".agent-team-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["phase"] == "DEV_PLAN"

    def test_saves_state_on_keyboard_interrupt(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.state.phase = Phase.DEV_IMPLEMENT

        def interrupted_run_once():
            raise KeyboardInterrupt()

        orch._run_once = interrupted_run_once
        orch.run()

        state_file = tmp_path / ".agent-team-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["phase"] == "DEV_IMPLEMENT"


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------

class TestStateRoundTrip:
    def test_save_and_load_roundtrip(self, orchestrator, tmp_project):
        _, tmp_path = tmp_project
        orchestrator._workflow_type = "feature"
        orchestrator.state.phase = Phase.DEV_TASKS
        orchestrator.state.feature = {"feature": "auth", "description": "Add auth"}
        orchestrator.state.pm_session = "pm_sess"
        orchestrator.state.dev_session = "dev_sess"
        orchestrator.state.pr_url = "https://github.com/org/repo/pull/42"

        orchestrator._save_state()
        loaded = orchestrator._load_state()

        assert loaded["phase"] == "DEV_TASKS"
        assert loaded["workflow_type"] == "feature"
        assert loaded["feature"]["feature"] == "auth"
        assert loaded["pm_session"] == "pm_sess"
        assert loaded["dev_session"] == "dev_sess"
        assert loaded["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_restore_state_from_loaded(self, tmp_project):
        """Simulate the full resume restore flow from main()."""
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
        assert orch2._resuming is True


# ---------------------------------------------------------------------------
# DONE clears state
# ---------------------------------------------------------------------------

class TestDoneClearsState:
    def test_done_phase_clears_state_file(self, tmp_project):
        config, tmp_path = tmp_project
        msg = MagicMock(spec=Messenger)
        msg.dry_run = True
        orch = Orchestrator(config, msg)

        # Stub all phases as no-ops, checkpoints return True
        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()

        # State file should NOT exist (cleared on DONE)
        assert not (tmp_path / ".agent-team-state.json").exists()
