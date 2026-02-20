#!/usr/bin/env python3
"""Worker pool manager - spawns multiple worker processes.

Usage:
    python worker_pool.py --workers 3      # Start 3 workers (static mode)
    python worker_pool.py --workers 2 --config my.yaml
    python worker_pool.py --auto-scale       # Enable dynamic scaling
    python worker_pool.py --auto-scale --min-workers 2 --max-workers 5
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    """Load configuration from YAML file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main():
    parser = argparse.ArgumentParser(description="Worker pool manager")

    parser.add_argument("--status", action="store_true", help="Query worker pool status and exit")

    # Static mode (default)
    parser.add_argument("--workers", type=int, default=None, help="Number of workers to spawn (static mode)")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    # Dynamic scaling mode
    parser.add_argument("--auto-scale", action="store_true", help="Enable dynamic worker scaling")
    parser.add_argument("--min-workers", type=int, default=None, help="Minimum workers (auto-scale mode)")
    parser.add_argument("--max-workers", type=int, default=None, help="Maximum workers (auto-scale mode)")
    parser.add_argument("--scale-up-threshold", type=float, default=None, help="Scale up threshold (auto-scale mode)")
    parser.add_argument("--scale-down-threshold", type=float, default=None, help="Scale down threshold (auto-scale mode)")
    parser.add_argument("--scale-cooldown", type=int, default=None, help="Scale cooldown in seconds")
    parser.add_argument("--idle-timeout", type=int, default=None, help="Idle timeout in seconds")
    parser.add_argument("--poll-interval", type=int, default=None, help="Poll interval in seconds")

    args = parser.parse_args()

    # Handle --status flag: query worker pool status without starting workers
    if args.status:
        config_path = args.config
        if not os.path.exists(config_path):
            config_path = os.path.join(os.path.dirname(__file__), args.config)

        if not os.path.exists(config_path):
            print(f"Error: Config file not found: {config_path}")
            sys.exit(1)

        config = load_config(config_path)

        # Get Redis config
        redis_config = config.get("redis_streams", {})
        redis_url = redis_config.get("url", "redis://localhost:6379")
        stream_name = redis_config.get("stream", "feature-requests")
        consumer_group = redis_config.get("consumer_group", "orchestrator-workers")

        # Load scaling config
        scaling_config_data = config.get("worker_scaling", {})
        scaling_config_data.setdefault("enabled", True)

        # Try to connect to Redis and get pending count
        try:
            import redis
            r = redis.from_url(redis_url, decode_responses=True)
            r.ping()

            # Get pending count using XPENDING
            result = r.xpending(stream_name, consumer_group)
            pending_count = result.get('pending', 0) if result else 0

            # Get stream info for total messages
            stream_info = r.xinfo_stream(stream_name)
            total_messages = stream_info.get('length', 0) if stream_info else 0

            print("Worker Pool Status")
            print("=" * 40)
            print(f"Redis URL: {redis_url}")
            print(f"Stream: {stream_name}")
            print(f"Consumer Group: {consumer_group}")
            print()
            print(f"Pending Messages: {pending_count}")
            print(f"Total Stream Messages: {total_messages}")
            print()

            # Display scaling config
            print("Scaling Configuration:")
            print(f"  Enabled: {scaling_config_data.get('enabled', False)}")
            print(f"  Min Workers: {scaling_config_data.get('min_workers', 1)}")
            print(f"  Max Workers: {scaling_config_data.get('max_workers', 10)}")
            print(f"  Scale Up Threshold: {scaling_config_data.get('scale_up_threshold', 2.0)}x")
            print(f"  Scale Down Threshold: {scaling_config_data.get('scale_down_threshold', 0.5)}x")
            print(f"  Scale Cooldown: {scaling_config_data.get('scale_cooldown', 60)}s")
            print(f"  Idle Timeout: {scaling_config_data.get('idle_timeout', 300)}s")
            print(f"  Poll Interval: {scaling_config_data.get('poll_interval', 5)}s")

        except ImportError:
            print("Error: redis package not installed")
            sys.exit(1)
        except Exception as e:
            print(f"Error connecting to Redis: {e}")
            sys.exit(1)

        sys.exit(0)

    config_path = args.config
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), args.config)

    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    # Load configuration
    config = load_config(config_path)

    # Determine mode: auto-scale or static
    use_auto_scale = args.auto_scale

    # Initialize scaling controller if in auto-scale mode
    controller = None
    if use_auto_scale:
        from src.scaling.config import ScalingConfig as ScalingConfigModel
        from src.scaling.controller import ScalingController

        # Load scaling config from yaml or use defaults
        scaling_config_data = config.get("worker_scaling", {})
        scaling_config_data.setdefault("enabled", True)
        scaling_config = ScalingConfigModel.from_dict(scaling_config_data)

        # CLI overrides
        if args.min_workers is not None:
            scaling_config.min_workers = args.min_workers
        if args.max_workers is not None:
            scaling_config.max_workers = args.max_workers
        if args.scale_up_threshold is not None:
            scaling_config.scale_up_threshold = args.scale_up_threshold
        if args.scale_down_threshold is not None:
            scaling_config.scale_down_threshold = args.scale_down_threshold
        if args.scale_cooldown is not None:
            scaling_config.scale_cooldown = args.scale_cooldown
        if args.idle_timeout is not None:
            scaling_config.idle_timeout = args.idle_timeout
        if args.poll_interval is not None:
            scaling_config.poll_interval = args.poll_interval

        # Get Redis config
        redis_config = config.get("redis_streams", {})
        redis_url = redis_config.get("url", "redis://localhost:6379")
        stream_name = redis_config.get("stream", "feature-requests")
        consumer_group = redis_config.get("consumer_group", "orchestrator-workers")

        controller = ScalingController(
            config=scaling_config,
            redis_url=redis_url,
            stream_name=stream_name,
            consumer_group=consumer_group,
            config_path=config_path,
            dry_run=args.dry_run,
        )

        print("Starting dynamic worker pool with auto-scaling...")
        print("Configuration:")
        print(f"  Min workers: {scaling_config.min_workers}")
        print(f"  Max workers: {scaling_config.max_workers}")
        print(f"  Scale up threshold: {scaling_config.scale_up_threshold}x")
        print(f"  Scale down threshold: {scaling_config.scale_down_threshold}x")
        print(f"  Cooldown: {scaling_config.scale_cooldown}s")
        print(f"  Idle timeout: {scaling_config.idle_timeout}s")
        print(f"  Poll interval: {scaling_config.poll_interval}s")

        print("\nScaling controller started.")

        # Start with minimum workers
        controller.ensure_min_workers()
        print(f"Scaling to {scaling_config.min_workers} workers (minimum)...")

    else:
        # Static mode (original behavior)
        worker_count = args.workers if args.workers is not None else 2
        print(f"Starting {worker_count} workers (static mode)...")

        workers = []

        def signal_handler(sig, frame):
            print("\nShutting down workers...")
            for proc in workers:
                proc.terminate()
            for proc in workers:
                proc.wait()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            for i in range(worker_count):
                worker_name = f"worker-{i+1}"
                cmd = [
                    sys.executable,
                    "worker.py",
                    "--config", config_path,
                    "--consumer", worker_name,
                ]
                if args.dry_run:
                    cmd.append("--dry-run")

                print(f"Starting {worker_name}: {' '.join(cmd)}")

                if args.dry_run:
                    print(f"  [DRY RUN] Would spawn worker {worker_name}")
                    continue

                proc = subprocess.Popen(
                    cmd,
                    cwd=os.getcwd(),
                )
                workers.append(proc)
                print(f"  Started {worker_name} with PID {proc.pid}")

            if args.dry_run:
                print("\n[DRY RUN] All workers would be started")
                return

            print(f"\nAll {len(workers)} workers started. Press Ctrl+C to stop.")

            # Wait for all workers
            while workers:
                # Check if any worker died
                for proc in workers:
                    if proc.poll() is not None:
                        print(f"Worker {proc.pid} exited, restarting...")
                        workers.remove(proc)
                        # Restart the worker
                        new_proc = subprocess.Popen(
                            cmd,
                            cwd=os.getcwd(),
                        )
                        workers.append(new_proc)
                        print(f"  Restarted worker with PID {new_proc.pid}")
                # Wait a bit before checking again
                time.sleep(5)

        except KeyboardInterrupt:
            print("\nShutting down workers...")
            for proc in workers:
                proc.terminate()
            for proc in workers:
                proc.wait()
            print("All workers stopped.")
        return

    # Auto-scale mode: use scaling controller
    def signal_handler(sig, frame):
        print("\nShutting down workers...")
        if controller:
            for worker in controller.workers[:]:
                controller.terminate_worker(worker)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        print(f"\nAll {controller.get_worker_count()} workers started. Press Ctrl+C to stop.")

        # Main scaling loop
        while True:
            # Clean up dead workers
            controller.cleanup_dead_workers()

            # Ensure minimum workers
            controller.ensure_min_workers()

            # Make scaling decision
            controller.make_scaling_decision()

            # Wait for next poll
            time.sleep(controller.config.poll_interval)

    except KeyboardInterrupt:
        print("\nShutting down workers...")
        for worker in controller.workers[:]:
            controller.terminate_worker(worker)
        print("All workers stopped.")


if __name__ == "__main__":
    main()
