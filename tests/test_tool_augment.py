"""Tests for tool_augment module.

Run: uv run pytest tests/test_tool_augment.py -v
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


from tool_augment import (
    DISCOVERY_TOOLS,
    ToolAugmentConfig,
    ToolAugmentLog,
    ToolAugmentor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_claude(response_json: dict | None = None, raw_text: str | None = None):
    """Create a mock run_claude that returns a controlled response."""
    def mock_run_claude(**kwargs):
        if response_json is not None:
            return {"result": json.dumps(response_json), "session_id": "test-session"}
        if raw_text is not None:
            return {"result": raw_text, "session_id": "test-session"}
        return {"result": "{}", "session_id": "test-session"}
    return mock_run_claude


class FakePhase:
    """Minimal phase stand-in for testing without importing orchestrator."""
    def __init__(self, name: str):
        self.name = name


@dataclass
class FakeState:
    feature: dict = field(default_factory=lambda: {"feature": "test", "description": "Add user auth"})


# ---------------------------------------------------------------------------
# ToolAugmentConfig
# ---------------------------------------------------------------------------

class TestToolAugmentConfig:
    def test_defaults(self):
        cfg = ToolAugmentConfig()
        assert cfg.enabled is False
        assert cfg.pre_stages is True
        assert cfg.post_stages is True
        assert cfg.run_tests_before_impl is True
        assert cfg.run_tests_after_impl is True
        assert cfg.timeout_per_hook == 120
        assert cfg.log_dir == "logs/augment"

    def test_from_dict(self):
        cfg = ToolAugmentConfig.from_dict({
            "enabled": True,
            "pre_stages": False,
            "timeout_per_hook": 60,
            "log_dir": "/tmp/logs",
        })
        assert cfg.enabled is True
        assert cfg.pre_stages is False
        assert cfg.post_stages is True  # default
        assert cfg.timeout_per_hook == 60
        assert cfg.log_dir == "/tmp/logs"

    def test_from_none(self):
        cfg = ToolAugmentConfig.from_dict(None)
        assert cfg.enabled is False

    def test_from_empty_dict(self):
        cfg = ToolAugmentConfig.from_dict({})
        assert cfg.enabled is False
        assert cfg.pre_stages is True


# ---------------------------------------------------------------------------
# ToolAugmentLog
# ---------------------------------------------------------------------------

class TestToolAugmentLog:
    def test_creates_log_dir(self, tmp_path):
        log_dir = str(tmp_path / "new_dir" / "logs")
        _log = ToolAugmentLog(log_dir, "run-001")
        assert Path(log_dir).exists()

    def test_write_creates_jsonl_file(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "run-001")
        log.write("test_record", foo="bar")

        assert log.path.exists()
        record = json.loads(log.path.read_text().strip())
        assert record["record_type"] == "test_record"
        assert record["run_id"] == "run-001"
        assert record["foo"] == "bar"
        assert "timestamp" in record

    def test_write_appends(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "run-002")
        log.write("first", x=1)
        log.write("second", x=2)

        lines = log.path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["record_type"] == "first"
        assert json.loads(lines[1])["record_type"] == "second"

    def test_write_tool_call(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "run-003")
        log.write_tool_call("DEV_SPECIFY", "pre", "prompt text", 150.5, {"key": "val"})

        record = json.loads(log.path.read_text().strip())
        assert record["record_type"] == "tool_call"
        assert record["phase"] == "DEV_SPECIFY"
        assert record["hook_type"] == "pre"
        assert record["duration_ms"] == 150.5
        assert record["findings"]["key"] == "val"

    def test_write_hook_summary(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "run-004")
        log.write_hook_summary("DEV_PLAN", "post", 200.0, {"validation_passed": True})

        record = json.loads(log.path.read_text().strip())
        assert record["record_type"] == "hook_summary"
        assert record["phase"] == "DEV_PLAN"

    def test_write_run_summary(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "run-005")
        log.write_run_summary("success", ["DEV_SPECIFY", "DEV_PLAN"], 4, 1200.0)

        record = json.loads(log.path.read_text().strip())
        assert record["record_type"] == "run_summary"
        assert record["outcome"] == "success"
        assert record["total_hooks"] == 4
        assert record["phases_augmented"] == ["DEV_SPECIFY", "DEV_PLAN"]

    def test_path_includes_run_id(self, tmp_path):
        log = ToolAugmentLog(str(tmp_path), "abc-123")
        assert "run_abc-123.jsonl" in str(log.path)


# ---------------------------------------------------------------------------
# Pre-hooks
# ---------------------------------------------------------------------------

class TestPreHooks:
    def _make_augmentor(self, tmp_path, run_claude_fn=None):
        cfg = ToolAugmentConfig(enabled=True)
        if run_claude_fn is None:
            run_claude_fn = _make_run_claude({"similar_features": [], "conventions": "PEP8"})
        return ToolAugmentor(
            project_path=str(tmp_path),
            config=cfg,
            run_id="test-run",
            run_claude_fn=run_claude_fn,
        )

    def test_pre_specify_invokes_claude(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"similar_features": [], "conventions": "PEP8"}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        result = aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())

        assert len(calls) == 1
        assert "Add user auth" in calls[0]["prompt"]
        assert calls[0]["allowed_tools"] == DISCOVERY_TOOLS
        assert result["conventions"] == "PEP8"

    def test_pre_plan_invokes_claude(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"verified_dependencies": ["flask"]}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        result = aug.run_pre_hook(FakePhase("DEV_PLAN"), FakeState())

        assert len(calls) == 1
        assert "dependency verifier" in calls[0]["prompt"].lower()
        assert result["verified_dependencies"] == ["flask"]

    def test_pre_tasks_invokes_claude(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"feasibility_score": 0.9}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        result = aug.run_pre_hook(FakePhase("DEV_TASKS"), FakeState())

        assert len(calls) == 1
        assert result["feasibility_score"] == 0.9

    def test_pre_implement_includes_pytest_tool(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"tests_green": true, "pre_flight_passed": true}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        result = aug.run_pre_hook(FakePhase("DEV_IMPLEMENT"), FakeState())

        assert "Bash(pytest *)" in calls[0]["allowed_tools"]
        assert result["pre_flight_passed"] is True

    def test_pre_implement_skips_pytest_when_disabled(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"pre_flight_passed": true}'}
        cfg = ToolAugmentConfig(enabled=True, run_tests_before_impl=False)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", mock_claude)

        aug.run_pre_hook(FakePhase("DEV_IMPLEMENT"), FakeState())

        assert "Bash(pytest *)" not in calls[0]["allowed_tools"]

    def test_pre_hook_handles_claude_error(self, tmp_path):
        def failing_claude(**kwargs):
            raise RuntimeError("Claude is down")
        aug = self._make_augmentor(tmp_path, failing_claude)

        result = aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())

        assert "error" in result
        assert result["validation_passed"] is False

    def test_pre_hook_parses_json_from_fenced_block(self, tmp_path):
        aug = self._make_augmentor(
            tmp_path,
            _make_run_claude(raw_text='Here is the analysis:\n```json\n{"conventions": "snake_case"}\n```'),
        )
        result = aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())
        assert result["conventions"] == "snake_case"


# ---------------------------------------------------------------------------
# Post-hooks
# ---------------------------------------------------------------------------

class TestPostHooks:
    def _make_augmentor(self, tmp_path, run_claude_fn=None):
        cfg = ToolAugmentConfig(enabled=True)
        if run_claude_fn is None:
            run_claude_fn = _make_run_claude({"validation_passed": True})
        return ToolAugmentor(
            project_path=str(tmp_path),
            config=cfg,
            run_id="test-run",
            run_claude_fn=run_claude_fn,
        )

    def test_post_specify_invokes_claude(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"referenced_but_missing": [], "validation_passed": true}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        result = aug.run_post_hook(FakePhase("DEV_SPECIFY"), FakeState())

        assert len(calls) == 1
        assert "spec validator" in calls[0]["prompt"].lower()
        assert result["validation_passed"] is True

    def test_post_implement_includes_validation_tools(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"tests_green": true, "validation_passed": true}'}
        aug = self._make_augmentor(tmp_path, mock_claude)

        _result = aug.run_post_hook(FakePhase("DEV_IMPLEMENT"), FakeState())

        assert "Bash(pytest *)" in calls[0]["allowed_tools"]
        assert "Bash(ruff *)" in calls[0]["allowed_tools"]

    def test_post_implement_skips_tools_when_disabled(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": '{"validation_passed": true}'}
        cfg = ToolAugmentConfig(enabled=True, run_tests_after_impl=False)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", mock_claude)

        aug.run_post_hook(FakePhase("DEV_IMPLEMENT"), FakeState())

        assert "Bash(pytest *)" not in calls[0]["allowed_tools"]
        assert "Bash(ruff *)" not in calls[0]["allowed_tools"]


# ---------------------------------------------------------------------------
# Hook dispatch
# ---------------------------------------------------------------------------

class TestHookDispatch:
    def _make_augmentor(self, tmp_path):
        cfg = ToolAugmentConfig(enabled=True)
        return ToolAugmentor(str(tmp_path), cfg, "test-run", _make_run_claude({"ok": True}))

    def test_returns_none_for_non_dev_phases(self, tmp_path):
        aug = self._make_augmentor(tmp_path)

        assert aug.run_pre_hook(FakePhase("INIT"), FakeState()) is None
        assert aug.run_pre_hook(FakePhase("PM_SUGGEST"), FakeState()) is None
        assert aug.run_pre_hook(FakePhase("REVIEW"), FakeState()) is None
        assert aug.run_pre_hook(FakePhase("CREATE_PR"), FakeState()) is None
        assert aug.run_pre_hook(FakePhase("DONE"), FakeState()) is None

    def test_returns_none_for_non_dev_post_phases(self, tmp_path):
        aug = self._make_augmentor(tmp_path)

        assert aug.run_post_hook(FakePhase("INIT"), FakeState()) is None
        assert aug.run_post_hook(FakePhase("PM_SUGGEST"), FakeState()) is None

    def test_dispatches_to_correct_pre_hooks(self, tmp_path):
        aug = self._make_augmentor(tmp_path)
        state = FakeState()

        for phase_name in ["DEV_SPECIFY", "DEV_PLAN", "DEV_TASKS", "DEV_IMPLEMENT"]:
            result = aug.run_pre_hook(FakePhase(phase_name), state)
            assert result is not None, f"Pre-hook returned None for {phase_name}"

    def test_dispatches_to_correct_post_hooks(self, tmp_path):
        aug = self._make_augmentor(tmp_path)
        state = FakeState()

        for phase_name in ["DEV_SPECIFY", "DEV_PLAN", "DEV_TASKS", "DEV_IMPLEMENT"]:
            result = aug.run_post_hook(FakePhase(phase_name), state)
            assert result is not None, f"Post-hook returned None for {phase_name}"


# ---------------------------------------------------------------------------
# Toggleability
# ---------------------------------------------------------------------------

class TestToggleability:
    def test_hooks_disabled_when_not_enabled(self, tmp_path):
        cfg = ToolAugmentConfig(enabled=False)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", _make_run_claude({"ok": True}))

        assert aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState()) is None
        assert aug.run_post_hook(FakePhase("DEV_SPECIFY"), FakeState()) is None

    def test_pre_hooks_disabled_when_pre_stages_false(self, tmp_path):
        cfg = ToolAugmentConfig(enabled=True, pre_stages=False)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", _make_run_claude({"ok": True}))

        assert aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState()) is None
        # Post hooks should still work
        result = aug.run_post_hook(FakePhase("DEV_SPECIFY"), FakeState())
        assert result is not None

    def test_post_hooks_disabled_when_post_stages_false(self, tmp_path):
        cfg = ToolAugmentConfig(enabled=True, post_stages=False)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", _make_run_claude({"ok": True}))

        # Pre hooks should still work
        result = aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())
        assert result is not None
        assert aug.run_post_hook(FakePhase("DEV_SPECIFY"), FakeState()) is None

    def test_timeout_passed_to_claude(self, tmp_path):
        calls = []
        def mock_claude(**kwargs):
            calls.append(kwargs)
            return {"result": "{}"}
        cfg = ToolAugmentConfig(enabled=True, timeout_per_hook=42)
        aug = ToolAugmentor(str(tmp_path), cfg, "test-run", mock_claude)

        aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())

        assert calls[0]["timeout"] == 42


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_finalize_writes_run_summary(self, tmp_path):
        cfg = ToolAugmentConfig(enabled=True, log_dir=str(tmp_path))
        aug = ToolAugmentor(str(tmp_path), cfg, "run-fin", _make_run_claude({"ok": True}))

        # Run a couple hooks to accumulate stats
        aug.run_pre_hook(FakePhase("DEV_SPECIFY"), FakeState())
        aug.run_post_hook(FakePhase("DEV_SPECIFY"), FakeState())
        aug.finalize("success")

        lines = aug.log.path.read_text().strip().split("\n")
        summary = json.loads(lines[-1])
        assert summary["record_type"] == "run_summary"
        assert summary["outcome"] == "success"
        assert summary["total_hooks"] == 2
        assert "DEV_SPECIFY" in summary["phases_augmented"]


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

class TestJsonParsing:
    def test_parse_direct_json(self):
        assert ToolAugmentor._parse_json_findings('{"key": "val"}') == {"key": "val"}

    def test_parse_fenced_json(self):
        text = "Here:\n```json\n{\"key\": \"val\"}\n```\nDone."
        assert ToolAugmentor._parse_json_findings(text) == {"key": "val"}

    def test_parse_embedded_json(self):
        text = "Analysis: {\"key\": \"val\"} and more text"
        assert ToolAugmentor._parse_json_findings(text) == {"key": "val"}

    def test_parse_fallback_on_garbage(self):
        result = ToolAugmentor._parse_json_findings("no json here at all")
        assert result["parse_error"] is True
        assert "no json here" in result["raw_response"]
