"""Unit tests for phase timer functionality in the orchestrator."""

import pytest
import threading
from unittest.mock import Mock, patch, MagicMock


class TestPeriodicCallbackRescheduling:
    """Tests for periodic callback rescheduling behavior.

    This tests the key feature where _periodic_status_update
    reschedules itself by calling _start_phase_timer again.
    """

    def test_periodic_callback_reschedules_on_completion(self):
        """Test that periodic status update callback reschedules itself.

        When _periodic_status_update is called, it should:
        1. Display the phase status
        2. Call _start_phase_timer again to schedule the next update
        """
        # Create a mock orchestrator
        mock_orchestrator = Mock()

        # Set up the phase_start_time to simulate phase running
        mock_orchestrator._phase_start_time = 1000.0
        mock_orchestrator._display_phase_status = Mock()

        # Import the actual method to test
        from orchestrator import Orchestrator

        # Bind the method to our mock
        periodic_update = Orchestrator._periodic_status_update

        # Call the periodic update
        periodic_update(mock_orchestrator, "IMPLEMENT")

        # Verify _display_phase_status was called
        mock_orchestrator._display_phase_status.assert_called_once_with("IMPLEMENT")

        # Verify _start_phase_timer was called to reschedule
        mock_orchestrator._start_phase_timer.assert_called_once_with("IMPLEMENT")

    def test_periodic_callback_does_not_reschedule_when_phase_ended(self):
        """Test that periodic callback does NOT reschedule when phase has ended.

        When _phase_start_time is None (phase ended), the callback should:
        1. NOT display status
        2. NOT call _start_phase_timer
        """
        # Create a mock orchestrator
        mock_orchestrator = Mock()

        # Set up the phase_start_time as None to simulate phase ended
        mock_orchestrator._phase_start_time = None

        # Import the actual method to test
        from orchestrator import Orchestrator

        # Bind the method to our mock
        periodic_update = Orchestrator._periodic_status_update

        # Call the periodic update
        periodic_update(mock_orchestrator, "IMPLEMENT")

        # Verify _display_phase_status was NOT called
        mock_orchestrator._display_phase_status.assert_not_called()

        # Verify _start_phase_timer was NOT called (no rescheduling)
        mock_orchestrator._start_phase_timer.assert_not_called()

    def test_periodic_callback_reschedules_multiple_times(self):
        """Test that callback can reschedule multiple times consecutively.

        This verifies the recursive rescheduling behavior works correctly.
        """
        call_count = 0
        original_phase_start_time = 1000.0

        # Create a mock that tracks rescheduling calls
        mock_orchestrator = Mock()
        mock_orchestrator._phase_start_time = original_phase_start_time

        from orchestrator import Orchestrator

        # First call
        Orchestrator._periodic_status_update(mock_orchestrator, "IMPLEMENT")
        assert mock_orchestrator._start_phase_timer.call_count == 1

        # Reset mocks for second call simulation
        mock_orchestrator.reset_mock()
        mock_orchestrator._phase_start_time = original_phase_start_time

        # Second call
        Orchestrator._periodic_status_update(mock_orchestrator, "IMPLEMENT")
        assert mock_orchestrator._start_phase_timer.call_count == 1

    @patch('orchestrator.threading.Timer')
    def test_start_phase_timer_cancels_existing_timer(self, mock_timer_class):
        """Test that _start_phase_timer cancels any existing timer before starting new one.

        This ensures no duplicate timers run simultaneously.
        """
        # Create existing timer that should be cancelled
        existing_timer = Mock()

        # Create mock orchestrator with side_effect to call the actual cancel logic
        mock_orchestrator = MagicMock()
        mock_orchestrator._phase_timer = existing_timer

        # Set up _cancel_phase_timer to actually set _phase_timer to None
        # and call cancel on the existing timer
        def cancel_side_effect():
            existing_timer.cancel()
            mock_orchestrator._phase_timer = None
        mock_orchestrator._cancel_phase_timer.side_effect = cancel_side_effect
        mock_orchestrator._get_phase_status_interval.return_value = 30

        # Configure mock timer to return from Timer()
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        from orchestrator import Orchestrator

        Orchestrator._start_phase_timer(mock_orchestrator, "IMPLEMENT")

        # Verify existing timer was cancelled
        existing_timer.cancel.assert_called_once()

        # Verify new timer was started
        mock_timer.start.assert_called_once()

    def test_cancel_phase_timer_cancels_and_clears(self):
        """Test that _cancel_phase_timer properly cancels and clears timer."""
        mock_orchestrator = Mock()
        existing_timer = Mock()
        mock_orchestrator._phase_timer = existing_timer

        from orchestrator import Orchestrator

        Orchestrator._cancel_phase_timer(mock_orchestrator)

        # Verify timer was cancelled
        existing_timer.cancel.assert_called_once()

        # Verify timer was set to None
        assert mock_orchestrator._phase_timer is None

    def test_cancel_phase_timer_handles_none(self):
        """Test that _cancel_phase_timer handles None timer gracefully."""
        mock_orchestrator = Mock()
        mock_orchestrator._phase_timer = None

        from orchestrator import Orchestrator

        # Should not raise any exception
        Orchestrator._cancel_phase_timer(mock_orchestrator)


class TestPhaseTimerIntegration:
    """Integration-style tests for phase timer with actual threading."""

    def test_timer_creates_daemon_thread(self):
        """Test that created timer is a daemon thread."""
        # We need to patch threading.Timer to avoid actual timer execution
        with patch('orchestrator.threading.Timer') as mock_timer_class:
            mock_timer = Mock()
            mock_timer_class.return_value = mock_timer

            # Create a minimal mock orchestrator
            mock_orchestrator = Mock()
            mock_orchestrator._phase_timer = None
            mock_orchestrator._get_phase_status_interval = Mock(return_value=30)

            from orchestrator import Orchestrator

            Orchestrator._start_phase_timer(mock_orchestrator, "IMPLEMENT")

            # Verify Timer was created with daemon=True
            mock_timer_class.assert_called_once()
            assert mock_timer.daemon is True
            mock_timer.start.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
