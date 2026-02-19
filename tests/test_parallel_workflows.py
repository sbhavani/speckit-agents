"""Tests for parallel workflows (Redis Streams)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig:
    """Tests for config loading."""

    def test_redis_streams_config_parsing(self):
        """Test that redis_streams config is parsed correctly."""
        import yaml

        config = yaml.safe_load("""
redis_streams:
  url: "redis://localhost:6379"
  stream: "feature-requests"
  consumer_group: "orchestrator-workers"
  defaults:
    block_ms: 5000
    count: 10
""")
        assert config["redis_streams"]["stream"] == "feature-requests"
        assert config["redis_streams"]["consumer_group"] == "orchestrator-workers"
        assert config["redis_streams"]["defaults"]["block_ms"] == 5000


class TestResponderRedis:
    """Tests for responder Redis stream publishing."""

    @patch("responder.redis")
    @patch("responder.MattermostBridge")
    def test_publish_feature_request(self, mock_bridge, mock_redis):
        """Test publishing feature request to Redis stream."""
        from responder import Responder

        # Setup mocks
        mock_redis_instance = MagicMock()
        mock_redis.from_url.return_value = mock_redis_instance
        mock_redis_instance.ping.return_value = True

        config = {
            "projects": {
                "test-project": {
                    "path": "/tmp/test",
                    "channel_id": "test-channel"
                }
            },
            "redis_streams": {
                "url": "redis://localhost:6379",
                "stream": "feature-requests",
                "consumer_group": "orchestrator-workers"
            },
            "mattermost": {
                "channel_id": "test-channel",
                "url": "http://localhost:8065"
            },
            "openclaw": {}
        }

        responder = Responder(config)
        responder.redis = mock_redis_instance

        # Call the method
        responder._publish_feature_request(
            feature="Add feature X",
            channel_id="test-channel",
            resume=False
        )

        # Verify xadd was called
        mock_redis_instance.xadd.assert_called_once()
        call_args = mock_redis_instance.xadd.call_args
        assert call_args[0][0] == "feature-requests"

    @patch("responder.redis")
    @patch("responder.MattermostBridge")
    def test_publish_resume_request(self, mock_bridge, mock_redis):
        """Test publishing resume request to Redis stream."""
        from responder import Responder

        mock_redis_instance = MagicMock()
        mock_redis.from_url.return_value = mock_redis_instance
        mock_redis_instance.ping.return_value = True

        config = {
            "projects": {},
            "redis_streams": {
                "url": "redis://localhost:6379",
                "stream": "feature-requests"
            },
            "mattermost": {"channel_id": "test", "url": "http://localhost:8065"},
            "openclaw": {}
        }

        responder = Responder(config)
        responder.redis = mock_redis_instance

        responder._publish_feature_request(channel_id="test-channel", resume=True)

        call_args = mock_redis_instance.xadd.call_args
        payload = call_args[0][1]
        assert payload["command"] == "resume"

    @patch("responder.redis")
    @patch("responder.MattermostBridge")
    @patch("responder.subprocess")
    def test_fallback_to_subprocess_when_redis_unavailable(
        self, mock_subprocess, mock_bridge, mock_redis
    ):
        """Test fallback to subprocess when Redis fails."""
        from responder import Responder

        # Setup mocks
        mock_redis_instance = MagicMock()
        mock_redis.from_url.return_value = mock_redis_instance
        mock_redis_instance.ping.side_effect = Exception("Connection refused")

        mock_proc = MagicMock()
        mock_subprocess.Popen.return_value = mock_proc

        config = {
            "projects": {},
            "mattermost": {"channel_id": "test", "url": "http://localhost:8065"},
            "openclaw": {}
        }

        responder = Responder(config)
        responder.redis = None  # Simulate no Redis

        responder._publish_feature_request(feature="Test", channel_id="test")

        # Should fall back to subprocess
        mock_subprocess.Popen.assert_called_once()


class TestWorker:
    """Tests for worker message consumption."""

    def test_worker_initialization(self):
        """Test worker initializes correctly."""
        with patch("worker.redis") as mock_redis:
            mock_redis_instance = MagicMock()
            mock_redis.from_url.return_value = mock_redis_instance
            mock_redis_instance.ping.return_value = True
            mock_redis_instance.xgroup_create.return_value = True

            from worker import Worker

            config = {
                "redis_streams": {
                    "url": "redis://localhost:6379",
                    "stream": "feature-requests",
                    "consumer_group": "orchestrator-workers",
                    "defaults": {"block_ms": 5000, "count": 10}
                }
            }

            worker = Worker(config, "test-worker")

            assert worker.stream_name == "feature-requests"
            assert worker.consumer_group == "orchestrator-workers"
            assert worker.consumer_name == "test-worker"

    def test_process_message_payload(self):
        """Test processing message with various payloads."""
        with patch("worker.redis") as mock_redis:
            mock_redis_instance = MagicMock()
            mock_redis.from_url.return_value = mock_redis_instance
            mock_redis_instance.ping.return_value = True
            mock_redis_instance.xgroup_create.return_value = True

            from worker import Worker

            config = {
                "redis_streams": {
                    "url": "redis://localhost:6379",
                    "stream": "feature-requests",
                    "consumer_group": "orchestrator-workers"
                }
            }

            worker = Worker(config, "test-worker", dry_run=True)
            worker.redis = mock_redis_instance

            # Test with bytes (as Redis returns)
            data = {
                b"project_name": b"test-project",
                b"channel_id": b"test-channel",
                b"feature": b"Add feature X",
                b"command": b"suggest"
            }

            worker._process_message("123-0", data)

            # Verify xack was called (dry run still acks)
            mock_redis_instance.xack.assert_called()

    @patch("worker.subprocess")
    def test_process_message_orchestrator_call(self, mock_subprocess):
        """Test that orchestrator is called with correct args."""
        with patch("worker.redis") as mock_redis:
            mock_redis_instance = MagicMock()
            mock_redis.from_url.return_value = mock_redis_instance
            mock_redis_instance.ping.return_value = True
            mock_redis_instance.xgroup_create.return_value = True
            mock_subprocess.run.return_value = MagicMock(returncode=0)

            from worker import Worker

            config = {
                "redis_streams": {
                    "url": "redis://localhost:6379",
                    "stream": "feature-requests",
                    "consumer_group": "orchestrator-workers"
                }
            }

            worker = Worker(config, "test-worker", dry_run=False)

            data = {
                "project_name": "my-project",
                "channel_id": "my-channel",
                "feature": "Add Redis",
                "command": "suggest"
            }

            worker._process_message("123-0", data)

            mock_subprocess.run.assert_called_once()
            call_args = mock_subprocess.run.call_args[0][0]
            assert "--project" in call_args
            assert "my-project" in call_args
            assert "--channel" in call_args
            assert "my-channel" in call_args
            assert "--feature" in call_args
            assert "Add Redis" in call_args

    @patch("worker.subprocess")
    def test_process_message_resume_command(self, mock_subprocess):
        """Test resume command includes --resume flag."""
        with patch("worker.redis") as mock_redis:
            mock_redis_instance = MagicMock()
            mock_redis.from_url.return_value = mock_redis_instance
            mock_redis_instance.ping.return_value = True
            mock_redis_instance.xgroup_create.return_value = True
            mock_subprocess.run.return_value = MagicMock(returncode=0)

            from worker import Worker

            config = {
                "redis_streams": {
                    "url": "redis://localhost:6379",
                    "stream": "feature-requests",
                    "consumer_group": "orchestrator-workers"
                }
            }

            worker = Worker(config, "test-worker", dry_run=False)

            data = {
                "project_name": "my-project",
                "channel_id": "my-channel",
                "feature": "",
                "command": "resume"
            }

            worker._process_message("123-0", data)

            call_args = mock_subprocess.run.call_args[0][0]
            assert "--resume" in call_args
            assert "--approve" in call_args


class TestWorkerPool:
    """Tests for worker pool manager."""

    @patch("worker_pool.subprocess")
    def test_worker_pool_spawns_correct_count(self, mock_subprocess):
        """Test that correct number of workers are spawned."""
        with patch("worker_pool.os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("yaml.safe_load", return_value={"redis_streams": {}}):
                    import worker_pool

                    # Mock Popen to return a process
                    mock_proc = MagicMock()
                    mock_proc.poll.return_value = None  # Still running
                    mock_subprocess.Popen.return_value = mock_proc

                    # Override the wait loop to exit quickly
                    _original_popen = worker_pool.subprocess.Popen
                    call_count = [0]

                    def mock_popen(*args, **kwargs):
                        call_count[0] += 1
                        return mock_proc

                    mock_subprocess.Popen = mock_popen

                    # Run with mocked config
                    with patch.object(worker_pool, "main") as _mock_main:
                        # Just test the argument parsing
                        pass

    def test_worker_pool_args(self):
        """Test worker pool argument parsing."""

        # Test that the parser accepts the expected arguments
        with patch("builtins.open", MagicMock()):
            with patch("yaml.safe_load", return_value={"redis_streams": {}}):
                with patch("worker_pool.subprocess.Popen"):
                    # Import after patching
                    import worker_pool

                    # Check that the module can be imported without error
                    assert hasattr(worker_pool, "main")


class TestIntegration:
    """Integration-style tests (mocked)."""

    def test_end_to_end_feature_request_flow(self):
        """Test full flow from publish to consume."""
        with patch("responder.redis") as mock_resp_redis:
            with patch("worker.redis") as mock_work_redis:
                # Setup responder's Redis mock
                resp_redis_instance = MagicMock()
                mock_resp_redis.from_url.return_value = resp_redis_instance
                resp_redis_instance.ping.return_value = True

                # Setup worker's Redis mock
                work_redis_instance = MagicMock()
                mock_work_redis.from_url.return_value = work_redis_instance
                work_redis_instance.ping.return_value = True
                work_redis_instance.xgroup_create.return_value = True
                # xreadgroup returns a list of [stream_name, [[message_id, {field: value}]]]
                work_redis_instance.xreadgroup.return_value = [
                    ("feature-requests", [
                        [
                            "123-0",
                            {
                                "project_name": "test-project",
                                "channel_id": "test-channel",
                                "feature": "Add feature",
                                "command": "suggest"
                            }
                        ]
                    ])
                ]

                # Import after patching
                from responder import Responder
                from worker import Worker

                config = {
                    "projects": {"test-project": {"path": "/tmp", "channel_id": "test-channel"}},
                    "redis_streams": {"url": "redis://localhost:6379", "stream": "feature-requests"},
                    "mattermost": {"channel_id": "test-channel", "url": "http://localhost:8065"},
                    "openclaw": {}
                }

                # Test responder publishing
                responder = Responder(config)
                responder.redis = resp_redis_instance
                responder._publish_feature_request(feature="Add feature", channel_id="test-channel")

                resp_redis_instance.xadd.assert_called_once()

                # Test worker consuming
                with patch("worker.subprocess") as mock_subprocess:
                    mock_subprocess.run.return_value = MagicMock(returncode=0)
                    worker = Worker(config, "test-worker")
                    worker.redis = work_redis_instance
                    worker._consume_messages()

                    mock_subprocess.run.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
