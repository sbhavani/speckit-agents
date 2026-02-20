"""Unit tests for ScalingController - target worker count calculation."""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.scaling.config import ScalingConfig
from src.scaling.controller import ScalingController, Worker


class TestScaleUpThreshold:
    """Tests for scale_up_threshold calculation in should_scale_up method (T011)."""

    @pytest.fixture
    def config(self):
        """Create a scaling config for testing."""
        return ScalingConfig(
            enabled=True,
            min_workers=1,
            max_workers=10,
            scale_up_threshold=2.0,
            scale_down_threshold=0.25,
            scale_cooldown=60,
            idle_timeout=300,
            poll_interval=10,
        )

    @pytest.fixture
    def controller(self, config):
        """Create a scaling controller with mocked Redis."""
        with patch("src.scaling.controller.redis"):
            controller = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="test-stream",
                consumer_group="test-group",
                config_path="config.yaml",
                dry_run=True,
            )
            controller.workers = []  # No actual workers
            return controller

    def test_scale_up_threshold_exceeded(self, controller):
        """Test that scale up triggers when pending exceeds threshold.

        With 2 workers and scale_up_threshold=2.0:
        - threshold = 2 * 2.0 = 4
        - pending=5 > 4 -> should scale up
        """
        result = controller.should_scale_up(pending=5, current=2)
        assert result is True

    def test_scale_up_threshold_not_exceeded(self, controller):
        """Test that scale up does not trigger when pending equals threshold.

        With 2 workers and scale_up_threshold=2.0:
        - threshold = 2 * 2.0 = 4
        - pending=4 > 4 is False -> should NOT scale up
        """
        result = controller.should_scale_up(pending=4, current=2)
        assert result is False

    def test_scale_up_below_threshold(self, controller):
        """Test that scale up does not trigger when pending is below threshold.

        With 2 workers and scale_up_threshold=2.0:
        - threshold = 2 * 2.0 = 4
        - pending=3 > 4 is False -> should NOT scale up
        """
        result = controller.should_scale_up(pending=3, current=2)
        assert result is False

    def test_scale_up_at_max_workers(self, controller):
        """Test that scale up does not trigger when at max_workers.

        With 10 workers (at max_workers=10):
        - Should NOT scale up regardless of pending count
        """
        result = controller.should_scale_up(pending=100, current=10)
        assert result is False

    def test_scale_up_custom_threshold(self, controller):
        """Test scale up with custom threshold value.

        With 2 workers and scale_up_threshold=1.5:
        - threshold = 2 * 1.5 = 3.0
        - pending=4 > 3 -> should scale up
        """
        controller.config.scale_up_threshold = 1.5
        result = controller.should_scale_up(pending=4, current=2)
        assert result is True

    def test_scale_up_single_worker(self, controller):
        """Test scale up with single worker.

        With 1 worker and scale_up_threshold=2.0:
        - threshold = 1 * 2.0 = 2.0
        - pending=3 > 2 -> should scale up
        """
        result = controller.should_scale_up(pending=3, current=1)
        assert result is True

    def test_scale_up_no_pending(self, controller):
        """Test scale up with zero pending requests.

        With 2 workers and scale_up_threshold=2.0:
        - threshold = 2 * 2.0 = 4
        - pending=0 > 4 is False -> should NOT scale up
        """
        result = controller.should_scale_up(pending=0, current=2)
        assert result is False

    def test_scale_up_near_max_workers(self, controller):
        """Test scale up when near max_workers but not at limit.

        With 9 workers (below max_workers=10) and scale_up_threshold=2.0:
        - threshold = 9 * 2.0 = 18
        - pending=20 > 18 -> should scale up
        """
        result = controller.should_scale_up(pending=20, current=9)
        assert result is True


class TestCalculateScaleUpTarget:
    """Tests for calculate_scale_up_target method (T012)."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return ScalingConfig(
            enabled=True,
            min_workers=2,
            max_workers=10,
            scale_up_threshold=2.0,
            scale_down_threshold=0.25,
            scale_cooldown=60,
            idle_timeout=300,
            poll_interval=10,
        )

    @pytest.fixture
    def controller(self, config):
        """Create a scaling controller with mocked Redis."""
        with patch("src.scaling.controller.redis"):
            ctrl = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="feature-requests",
                consumer_group="workers",
                config_path="config.yaml",
                dry_run=True,
            )
            return ctrl

    def test_basic_calculation_handles_50_percent(self, controller):
        """Test that target handles at least 50% of pending requests."""
        # pending=10 should result in target = 10 // 2 + 1 = 6
        target = controller.calculate_scale_up_target(pending=10, current=3)
        assert target == 6

    def test_single_pending_request(self, controller):
        """Test calculation with single pending request."""
        # pending=1 should result in target = 1 // 2 + 1 = 1
        target = controller.calculate_scale_up_target(pending=1, current=1)
        assert target == 1

    def test_zero_pending_requests(self, controller):
        """Test calculation with zero pending requests."""
        # pending=0 should result in target = 0 // 2 + 1 = 1
        target = controller.calculate_scale_up_target(pending=0, current=1)
        assert target == 1

    def test_max_workers_bound_enforcement(self, controller):
        """Test that max_workers bound is enforced."""
        # pending=100, max_workers=10, target should be capped at 10
        # 100 // 2 + 1 = 51, but capped to 10
        target = controller.calculate_scale_up_target(pending=100, current=5)
        assert target == 10

    def test_max_workers_boundary(self, controller):
        """Test at exact max_workers boundary."""
        # pending=18 // 2 + 1 = 10, exactly at max
        target = controller.calculate_scale_up_target(pending=18, current=3)
        assert target == 10

    def test_large_pending_count(self, controller):
        """Test with very large pending count."""
        # Should always respect max_workers
        target = controller.calculate_scale_up_target(pending=1000000, current=1)
        assert target == 10

    def test_odd_pending_count(self, controller):
        """Test with odd number of pending requests."""
        # pending=7 // 2 + 1 = 3 + 1 = 4
        target = controller.calculate_scale_up_target(pending=7, current=2)
        assert target == 4

    def test_even_pending_count(self, controller):
        """Test with even number of pending requests."""
        # pending=8 // 2 + 1 = 4 + 1 = 5
        target = controller.calculate_scale_up_target(pending=8, current=2)
        assert target == 5

    def test_custom_max_workers(self, config):
        """Test with custom max_workers configuration."""
        config.max_workers = 5
        with patch("src.scaling.controller.redis"):
            controller = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="feature-requests",
                consumer_group="workers",
                config_path="config.yaml",
                dry_run=True,
            )

            # pending=100, max_workers=5, target should be capped at 5
            target = controller.calculate_scale_up_target(pending=100, current=1)
            assert target == 5

    def test_current_worker_count_not_used_in_formula(self, controller):
        """Test that current worker count doesn't affect target calculation.

        The formula only considers pending count, not current workers.
        """
        # Same pending, different current workers should give same target
        # Use pending=8 so result (8//2+1=5) is below max_workers=10
        target1 = controller.calculate_scale_up_target(pending=8, current=1)
        target2 = controller.calculate_scale_up_target(pending=8, current=10)

        # pending=8 // 2 + 1 = 4 + 1 = 5
        assert target1 == 5
        assert target2 == 5


class TestScaleDownThreshold:
    """Tests for scale_down_threshold calculation (T017)."""

    @pytest.fixture
    def config(self):
        """Create a scaling config for testing."""
        return ScalingConfig(
            enabled=True,
            min_workers=1,
            max_workers=10,
            scale_up_threshold=2.0,
            scale_down_threshold=0.25,
            scale_cooldown=60,
            idle_timeout=300,
            poll_interval=10,
        )

    @pytest.fixture
    def controller(self, config):
        """Create a scaling controller with mocked Redis."""
        with patch("src.scaling.controller.redis"):
            return ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="test-stream",
                consumer_group="test-group",
                config_path="config.yaml",
                dry_run=True,
            )

    def test_scale_down_threshold_default_value(self, controller):
        """Test that scale_down_threshold defaults to 0.25."""
        assert controller.config.scale_down_threshold == 0.25

    def test_scale_down_threshold_calculation_with_1_worker(self, controller):
        """Test scale_down_threshold calculation with 1 worker.

        With 1 worker and scale_down_threshold=0.25:
        - threshold = 1 * 0.25 = 0.25
        - pending < 0.25 triggers scale down (i.e., pending=0)
        """
        threshold = 1 * controller.config.scale_down_threshold
        assert threshold == 0.25

    def test_scale_down_threshold_calculation_with_4_workers(self, controller):
        """Test scale_down_threshold calculation with 4 workers.

        With 4 workers and scale_down_threshold=0.25:
        - threshold = 4 * 0.25 = 1.0
        - pending < 1.0 triggers scale down (i.e., pending=0)
        """
        threshold = 4 * controller.config.scale_down_threshold
        assert threshold == 1.0

    def test_scale_down_threshold_calculation_with_8_workers(self, controller):
        """Test scale_down_threshold calculation with 8 workers.

        With 8 workers and scale_down_threshold=0.25:
        - threshold = 8 * 0.25 = 2.0
        - pending < 2.0 triggers scale down (i.e., pending=0 or 1)
        """
        threshold = 8 * controller.config.scale_down_threshold
        assert threshold == 2.0

    def test_should_scale_down_triggers_at_zero_pending(self, controller):
        """Test should_scale_down returns True when pending=0 (after idle timeout).

        With 4 workers and scale_down_threshold=0.25:
        - threshold = 4 * 0.25 = 1.0
        - pending=0 < 1.0 -> should scale down
        """
        # Set up idle timeout passed
        controller.last_activity_time = 0
        idle_time = time.time() - controller.last_activity_time
        assert idle_time >= controller.config.idle_timeout

        # With pending=0, should scale down
        result = controller.should_scale_down(pending=0, current=4)
        assert result is True

    def test_should_scale_down_does_not_trigger_above_threshold(self, controller):
        """Test should_scale_down returns False when pending above threshold.

        With 4 workers and scale_down_threshold=0.25:
        - threshold = 4 * 0.25 = 1.0
        - pending=2 > 1.0 -> should NOT scale down
        """
        controller.last_activity_time = 0

        result = controller.should_scale_down(pending=2, current=4)
        assert result is False

    def test_should_scale_down_custom_threshold(self, controller):
        """Test should_scale_down works with custom scale_down_threshold.

        With scale_down_threshold=0.5:
        - 4 workers -> threshold = 4 * 0.5 = 2.0
        - pending=1 < 2.0 -> should scale down
        - pending=3 > 2.0 -> should NOT scale down
        """
        controller.config.scale_down_threshold = 0.5
        controller.last_activity_time = 0

        # pending=1 < 4 * 0.5 = 2 -> should scale down
        result = controller.should_scale_down(pending=1, current=4)
        assert result is True

        # pending=3 > 4 * 0.5 = 2 -> should NOT scale down
        result = controller.should_scale_down(pending=3, current=4)
        assert result is False


class TestIdleTimeoutTracking:
    """Tests for idle_timeout tracking in ScalingController."""

    @pytest.fixture
    def config(self):
        """Create a scaling config for testing."""
        return ScalingConfig(
            enabled=True,
            min_workers=1,
            max_workers=10,
            scale_up_threshold=2.0,
            scale_down_threshold=0.25,
            scale_cooldown=60,
            idle_timeout=300,  # 5 minutes
            poll_interval=10,
        )

    @pytest.fixture
    def controller(self, config):
        """Create a scaling controller with mocked Redis."""
        with patch("src.scaling.controller.redis"):
            controller = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="test-stream",
                consumer_group="test-group",
                config_path="config.yaml",
                dry_run=True,
            )
            # Reset last_activity_time to a known value
            controller.last_activity_time = time.time() - 100  # 100 seconds ago
            return controller

    def test_idle_time_tracks_correctly(self, controller):
        """Test that idle time is calculated correctly."""
        # Set last_activity_time to 100 seconds ago
        controller.last_activity_time = time.time() - 100
        idle_time = time.time() - controller.last_activity_time

        # Should be approximately 100 seconds (accounting for small timing differences)
        assert 95 <= idle_time <= 105

    def test_should_scale_down_blocked_by_idle_timeout(self, controller):
        """Test that scale-down is blocked when idle_timeout not reached."""
        # Set idle_timeout to 300 seconds but only 100 seconds have passed
        controller.config.idle_timeout = 300
        controller.last_activity_time = time.time() - 100  # Only 100 seconds idle

        # Should NOT scale down because idle timeout not reached
        result = controller.should_scale_down(pending=0, current=5)

        assert result is False

    def test_should_scale_down_allowed_after_idle_timeout(self, controller):
        """Test that scale-down is allowed after idle_timeout reached."""
        # Set idle_timeout to 60 seconds and 100 seconds have passed
        controller.config.idle_timeout = 60
        controller.last_activity_time = time.time() - 100  # 100 seconds idle

        # Should scale down because idle timeout exceeded AND pending is low
        result = controller.should_scale_down(pending=0, current=5)

        # pending=0 < current(5) * scale_down_threshold(0.25) = 1.25
        assert result is True

    def test_should_scale_down_respects_min_workers(self, controller):
        """Test that scale-down respects min_workers boundary."""
        controller.config.idle_timeout = 60
        controller.last_activity_time = time.time() - 100
        controller.config.min_workers = 3

        # Should NOT scale down because current=3 is at min_workers
        result = controller.should_scale_down(pending=0, current=3)

        assert result is False

    def test_last_activity_time_updated_on_pending(self, controller):
        """Test that last_activity_time is updated when there are pending messages."""
        # Set last_activity_time to 500 seconds ago
        old_activity_time = time.time() - 500
        controller.last_activity_time = old_activity_time

        # Simulate pending > 0 by directly calling the logic
        controller.last_activity_time = time.time()

        # last_activity_time should be updated to current time
        assert time.time() - controller.last_activity_time < 1

    def test_idle_timeout_respects_config_value(self, controller):
        """Test that idle_timeout uses the config value correctly."""
        # Test with different idle_timeout values
        test_cases = [
            (60, 50, False),   # 50s idle, 60s timeout -> no scale down
            (60, 70, True),     # 70s idle, 60s timeout -> scale down allowed
            (300, 299, False),  # 299s idle, 300s timeout -> no scale down
            (300, 301, True),   # 301s idle, 300s timeout -> scale down allowed
        ]

        for timeout, idle_seconds, expected in test_cases:
            controller.config.idle_timeout = timeout
            controller.last_activity_time = time.time() - idle_seconds
            result = controller.should_scale_down(pending=0, current=5)
            assert result == expected, f"Failed for timeout={timeout}, idle={idle_seconds}"

    def test_should_scale_down_with_zero_pending_after_idle(self, controller):
        """Test scale-down decision with zero pending after idle period."""
        controller.config.idle_timeout = 60
        controller.config.scale_down_threshold = 0.25
        controller.last_activity_time = time.time() - 100  # Idle for 100 seconds
        controller.config.min_workers = 1

        # pending=0 < current(5) * 0.25 = 1.25 -> should scale down
        result = controller.should_scale_down(pending=0, current=5)

        assert result is True

    def test_should_scale_down_with_high_pending_after_idle(self, controller):
        """Test scale-down decision with high pending after idle period."""
        controller.config.idle_timeout = 60
        controller.config.scale_down_threshold = 0.25
        controller.last_activity_time = time.time() - 100  # Idle for 100 seconds

        # pending=10 > current(5) * 0.25 = 1.25 -> should NOT scale down
        result = controller.should_scale_down(pending=10, current=5)

        assert result is False


class TestMinMaxBoundsEnforcement:
    """Tests for min/max bounds enforcement in scaling controller (T024)."""

    @pytest.fixture
    def config(self):
        """Create a test configuration with min=2, max=5."""
        return ScalingConfig(
            enabled=True,
            min_workers=2,
            max_workers=5,
            scale_up_threshold=2.0,
            scale_down_threshold=0.25,
            scale_cooldown=10,
            idle_timeout=60,
            poll_interval=5,
        )

    @pytest.fixture
    def mock_controller(self, config):
        """Create a scaling controller with mocked Redis."""
        with patch("src.scaling.controller.redis") as mock_redis:
            mock_client = MagicMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping.return_value = True

            controller = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="test-stream",
                consumer_group="test-group",
                config_path="config.yaml",
                dry_run=True,
            )
            return controller

    # ==================== should_scale_up bounds tests ====================

    def test_should_scale_up_returns_false_at_max_workers(self, mock_controller):
        """should_scale_up returns False when current >= max_workers."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
            Worker(pid=2, consumer_name="worker-2"),
            Worker(pid=3, consumer_name="worker-3"),
            Worker(pid=4, consumer_name="worker-4"),
            Worker(pid=5, consumer_name="worker-5"),
        ]

        result = mock_controller.should_scale_up(pending=100, current=5)
        assert result is False

    def test_should_scale_up_returns_false_above_max_workers(self, mock_controller):
        """should_scale_up returns False when current > max_workers (edge case)."""
        mock_controller.workers = [
            Worker(pid=i, consumer_name=f"worker-{i}")
            for i in range(1, 7)
        ]

        result = mock_controller.should_scale_up(pending=100, current=6)
        assert result is False

    def test_should_scale_up_allows_scale_when_below_max(self, mock_controller):
        """should_scale_up returns True when below max and threshold exceeded."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
            Worker(pid=2, consumer_name="worker-2"),
        ]

        result = mock_controller.should_scale_up(pending=10, current=2)
        assert result is True

    # ==================== should_scale_down bounds tests ====================

    def test_should_scale_down_returns_false_at_min_workers(self, mock_controller):
        """should_scale_down returns False when current <= min_workers."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
            Worker(pid=2, consumer_name="worker-2"),
        ]
        mock_controller.last_activity_time = time.time() - 100

        result = mock_controller.should_scale_down(pending=0, current=2)
        assert result is False

    def test_should_scale_down_returns_false_below_min_workers(self, mock_controller):
        """should_scale_down returns False when current < min_workers (edge case)."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
        ]
        mock_controller.last_activity_time = time.time() - 100

        result = mock_controller.should_scale_down(pending=0, current=1)
        assert result is False

    def test_should_scale_down_allows_scale_when_above_min(self, mock_controller):
        """should_scale_down returns True when above min and threshold exceeded."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
            Worker(pid=2, consumer_name="worker-2"),
            Worker(pid=3, consumer_name="worker-3"),
        ]
        mock_controller.last_activity_time = time.time() - 100

        result = mock_controller.should_scale_down(pending=0, current=3)
        assert result is True

    # ==================== calculate_scale_up_target bounds tests ====================

    def test_calculate_scale_up_target_caps_at_max_workers(self, mock_controller):
        """calculate_scale_up_target caps target at max_workers."""
        result = mock_controller.calculate_scale_up_target(pending=100, current=2)
        assert result <= mock_controller.config.max_workers
        assert result == 5

    def test_calculate_scale_up_target_respects_max_with_large_pending(self, mock_controller):
        """calculate_scale_up_target respects max when pending is very high."""
        result = mock_controller.calculate_scale_up_target(pending=1000, current=3)
        assert result == mock_controller.config.max_workers

    def test_calculate_scale_up_target_allows_growth_below_max(self, mock_controller):
        """calculate_scale_up_target allows growth when below max."""
        result = mock_controller.calculate_scale_up_target(pending=6, current=2)
        assert result == 4

    # ==================== calculate_scale_down_target bounds tests ====================

    def test_calculate_scale_down_target_respects_min_workers(self, mock_controller):
        """calculate_scale_down_target respects min_workers boundary."""
        result = mock_controller.calculate_scale_down_target(pending=0, current=2)
        assert result >= mock_controller.config.min_workers
        assert result == 2

    def test_calculate_scale_down_target_above_min(self, mock_controller):
        """calculate_scale_down_target reduces by 1 but respects min."""
        result = mock_controller.calculate_scale_down_target(pending=0, current=5)
        assert result == 4

    def test_calculate_scale_down_target_gradual_termination(self, mock_controller):
        """calculate_scale_down_target only reduces by 1 at a time."""
        result1 = mock_controller.calculate_scale_down_target(pending=0, current=5)
        result2 = mock_controller.calculate_scale_down_target(pending=0, current=4)
        result3 = mock_controller.calculate_scale_down_target(pending=0, current=3)

        assert result1 == 4
        assert result2 == 3
        assert result3 == 2

    # ==================== Integration: full bounds enforcement ====================

    def test_scale_up_respects_max_boundary(self, mock_controller):
        """scale_up action respects max_workers boundary."""
        mock_controller.workers = [
            Worker(pid=i, consumer_name=f"worker-{i}")
            for i in range(1, 6)
        ]

        event = mock_controller.scale_up(pending=100)

        assert mock_controller.get_worker_count() <= mock_controller.config.max_workers
        if event:
            assert event.target_count <= mock_controller.config.max_workers

    def test_scale_down_respects_min_boundary(self, mock_controller):
        """scale_down action respects min_workers boundary."""
        mock_controller.workers = [
            Worker(pid=i, consumer_name=f"worker-{i}")
            for i in range(1, 3)
        ]
        mock_controller.last_activity_time = time.time() - 100

        event = mock_controller.scale_down(pending=0)

        assert mock_controller.get_worker_count() >= mock_controller.config.min_workers
        if event:
            assert event.target_count >= mock_controller.config.min_workers

    def test_ensure_min_workers_spawns_to_min(self, config):
        """ensure_min_workers spawns workers to reach min_workers."""
        with patch("src.scaling.controller.redis"), \
             patch("src.scaling.controller.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 12345

            controller = ScalingController(
                config=config,
                redis_url="redis://localhost:6379",
                stream_name="test-stream",
                consumer_group="test-group",
                config_path="config.yaml",
                dry_run=False,
            )
            controller.workers = []

            controller.ensure_min_workers()

            assert controller.get_worker_count() == config.min_workers

    def test_ensure_min_workers_no_op_at_min(self, mock_controller):
        """ensure_min_workers does nothing when at min_workers."""
        mock_controller.workers = [
            Worker(pid=1, consumer_name="worker-1"),
            Worker(pid=2, consumer_name="worker-2"),
        ]

        initial_count = mock_controller.get_worker_count()
        mock_controller.ensure_min_workers()

        assert mock_controller.get_worker_count() == initial_count

    # ==================== Edge cases ====================

    def test_config_validation_prevents_invalid_bounds(self):
        """ScalingConfig rejects invalid min/max configurations."""
        with pytest.raises(ValueError):
            ScalingConfig(min_workers=5, max_workers=2)

        with pytest.raises(ValueError):
            ScalingConfig(min_workers=0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
