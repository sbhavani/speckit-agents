"""Tests for orchestrator resume functionality.

Run: uv run pytest tests/test_orchestrator.py -m "not integration"
"""

import json
from unittest.mock import MagicMock

import pytest

from orchestrator import (
    PHASE_SEQUENCE_FEATURE,
    PHASE_SEQUENCE_NORMAL,
    Messenger,
    Orchestrator,
    Phase,
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
        orch = Orchestrator(config, msg)

        for _, method_name, is_checkpoint in PHASE_SEQUENCE_NORMAL:
            if is_checkpoint:
                setattr(orch, method_name, lambda: True)
            else:
                setattr(orch, method_name, lambda: None)

        orch._run_once()
        assert not (tmp_path / ".agent-team-state.json").exists()
