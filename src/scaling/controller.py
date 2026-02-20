"""Scaling controller for dynamic worker pool management."""

import logging
import time
import subprocess
import sys
import os
from dataclasses import dataclass, field
from typing import List, Optional

import redis

from src.scaling.config import ScalingConfig

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    """Represents a running worker process."""

    pid: int
    consumer_name: str
    started_at: float = field(default_factory=time.time)
    status: str = "running"


@dataclass
class ScalingEvent:
    """Log entry for scaling actions."""

    timestamp: float
    action: str  # "scale_up", "scale_down", "no_change"
    pending_count: int
    worker_count: int
    target_count: int
    reason: str


class ScalingController:
    """Controls dynamic scaling of the worker pool based on queue depth."""

    def __init__(
        self,
        config: ScalingConfig,
        redis_url: str,
        stream_name: str,
        consumer_group: str,
        config_path: str,
        dry_run: bool = False,
    ):
        """Initialize the scaling controller.

        Args:
            config: Scaling configuration
            redis_url: Redis connection URL
            stream_name: Name of the Redis stream
            consumer_group: Consumer group name
            config_path: Path to config file for worker spawning
            dry_run: If True, only log actions without executing
        """
        self.config = config
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.config_path = config_path
        self.dry_run = dry_run

        self.workers: List[Worker] = []
        self.last_scale_time: float = 0
        self.last_activity_time: float = time.time()

        # Initialize Redis connection
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}")

    def get_pending_count(self) -> int:
        """Get the count of pending (unacknowledged) messages.

        Returns:
            Number of pending messages in the stream
        """
        try:
            # XPENDING returns dict with 'pending' key in redis-py 7.x
            result = self.redis.xpending(
                self.stream_name,
                self.consumer_group,
            )
            if result and isinstance(result, dict):
                return result.get('pending', 0) or 0
            return 0
        except redis.ResponseError as e:
            logger.warning(f"Error getting pending count: {e}")
            return 0

    def get_worker_count(self) -> int:
        """Get current worker count.

        Returns:
            Number of active workers
        """
        return len(self.workers)

    def spawn_worker(self, worker_name: str) -> Optional[Worker]:
        """Spawn a new worker process.

        Args:
            worker_name: Name for the new worker

        Returns:
            Worker instance if successful, None otherwise
        """
        cmd = [
            sys.executable,
            "worker.py",
            "--config", self.config_path,
            "--consumer", worker_name,
        ]
        if self.dry_run:
            logger.info(f"[DRY RUN] Would spawn worker {worker_name}")
            return Worker(pid=0, consumer_name=worker_name)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
            )
            worker = Worker(pid=proc.pid, consumer_name=worker_name)
            self.workers.append(worker)
            logger.info(f"Spawned worker {worker_name} with PID {proc.pid}")
            return worker
        except Exception as e:
            logger.error(f"Failed to spawn worker {worker_name}: {e}")
            return None

    def terminate_worker(self, worker: Worker) -> bool:
        """Terminate a worker process.

        Args:
            worker: Worker instance to terminate

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would terminate worker {worker.consumer_name}")
            return True

        try:
            # Try graceful termination first
            os.kill(worker.pid, 15)  # SIGTERM
            worker.status = "stopping"
            logger.info(f"Terminating worker {worker.consumer_name} (PID {worker.pid})")
            return True
        except ProcessLookupError:
            # Process already dead
            logger.warning(f"Worker {worker.consumer_name} already dead")
            self.workers.remove(worker)
            return True
        except Exception as e:
            logger.error(f"Failed to terminate worker {worker.consumer_name}: {e}")
            return False

    def calculate_scale_up_target(self, pending: int, current: int) -> int:
        """Calculate target worker count for scale-up.

        Args:
            pending: Current pending message count
            current: Current worker count

        Returns:
            Target worker count
        """
        # Target: handle at least 50% of pending requests concurrently
        target = pending // 2 + 1
        # Apply max bound
        target = min(target, self.config.max_workers)
        return target

    def calculate_scale_down_target(self, pending: int, current: int) -> int:
        """Calculate target worker count for scale-down.

        Args:
            pending: Current pending message count
            current: Current worker count

        Returns:
            Target worker count
        """
        # Target: reduce by 1 at a time for gradual termination
        target = max(current - 1, self.config.min_workers)
        return target

    def should_scale_up(self, pending: int, current: int) -> bool:
        """Determine if scale-up is needed.

        Args:
            pending: Current pending message count
            current: Current worker count

        Returns:
            True if should scale up
        """
        if current >= self.config.max_workers:
            return False
        if pending > current * self.config.scale_up_threshold:
            return True
        return False

    def should_scale_down(self, pending: int, current: int) -> bool:
        """Determine if scale-down is needed.

        Args:
            pending: Current pending message count
            current: Current worker count

        Returns:
            True if should scale down
        """
        if current <= self.config.min_workers:
            return False

        # Only scale down after idle timeout
        idle_time = time.time() - self.last_activity_time
        if idle_time < self.config.idle_timeout:
            return False

        if pending < current * self.config.scale_down_threshold:
            return True
        return False

    def scale_up(self, pending: int) -> Optional[ScalingEvent]:
        """Perform scale-up action.

        Args:
            pending: Current pending message count

        Returns:
            ScalingEvent if action taken, None otherwise
        """
        current = self.get_worker_count()
        target = self.calculate_scale_up_target(pending, current)

        if target <= current:
            return None

        # Check cooldown
        if time.time() - self.last_scale_time < self.config.scale_cooldown:
            logger.debug("Scale-up blocked by cooldown")
            return None

        logger.info(f"SCALE_UP: pending={pending}, workers={current} -> target={target}")

        # Spawn workers to reach target
        workers_to_spawn = target - current
        for i in range(workers_to_spawn):
            worker_name = f"worker-{current + i + 1}"
            self.spawn_worker(worker_name)

        self.last_scale_time = time.time()

        return ScalingEvent(
            timestamp=time.time(),
            action="scale_up",
            pending_count=pending,
            worker_count=current,
            target_count=target,
            reason="threshold exceeded",
        )

    def scale_down(self, pending: int) -> Optional[ScalingEvent]:
        """Perform scale-down action.

        Args:
            pending: Current pending message count

        Returns:
            ScalingEvent if action taken, None otherwise
        """
        current = self.get_worker_count()
        target = self.calculate_scale_down_target(pending, current)

        if target >= current:
            return None

        # Check cooldown
        if time.time() - self.last_scale_time < self.config.scale_cooldown:
            logger.debug("Scale-down blocked by cooldown")
            return None

        logger.info(f"SCALE_DOWN: pending={pending}, workers={current} -> target={target}")

        # Terminate excess workers (gradually - one at a time)
        workers_to_terminate = current - target
        terminated = 0
        for worker in self.workers[:]:
            if terminated >= workers_to_terminate:
                break
            if worker.status == "running":
                if self.terminate_worker(worker):
                    terminated += 1

        self.last_scale_time = time.time()

        return ScalingEvent(
            timestamp=time.time(),
            action="scale_down",
            pending_count=pending,
            worker_count=current,
            target_count=target,
            reason="idle timeout",
        )

    def make_scaling_decision(self) -> Optional[ScalingEvent]:
        """Make a scaling decision based on current state.

        Returns:
            ScalingEvent if action taken, None otherwise
        """
        pending = self.get_pending_count()
        current = self.get_worker_count()

        # Update last activity time
        if pending > 0:
            self.last_activity_time = time.time()

        # Check scale-up
        if self.should_scale_up(pending, current):
            return self.scale_up(pending)

        # Check scale-down
        if self.should_scale_down(pending, current):
            return self.scale_down(pending)

        # Log no change
        logger.debug(f"NO_CHANGE: pending={pending}, workers={current}")
        return ScalingEvent(
            timestamp=time.time(),
            action="no_change",
            pending_count=pending,
            worker_count=current,
            target_count=current,
            reason="within bounds",
        )

    def cleanup_dead_workers(self) -> None:
        """Remove dead workers from the worker list."""
        for worker in self.workers[:]:
            if worker.status == "running":
                try:
                    os.kill(worker.pid, 0)  # Check if process exists
                except OSError:
                    logger.warning(f"Worker {worker.consumer_name} (PID {worker.pid}) is dead")
                    self.workers.remove(worker)

    def ensure_min_workers(self) -> None:
        """Ensure at least min_workers are running."""
        current = self.get_worker_count()
        if current < self.config.min_workers:
            needed = self.config.min_workers - current
            logger.info(f"Ensuring minimum workers: spawning {needed}")
            for i in range(needed):
                worker_name = f"worker-{current + i + 1}"
                self.spawn_worker(worker_name)
