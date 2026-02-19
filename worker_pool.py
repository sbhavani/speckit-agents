#!/usr/bin/env python3
"""Worker pool manager - spawns multiple worker processes.

Usage:
    python worker_pool.py --workers 3      # Start 3 workers
    python worker_pool.py --workers 2 --config my.yaml
"""

import argparse
import os
import signal
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Worker pool manager")
    parser.add_argument("--workers", type=int, default=2, help="Number of workers to spawn")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    args = parser.parse_args()

    config_path = args.config
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), args.config)

    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    workers = []
    print(f"Starting {args.workers} workers...")

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
        for i in range(args.workers):
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
            import time
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nShutting down workers...")
        for proc in workers:
            proc.terminate()
        for proc in workers:
            proc.wait()
        print("All workers stopped.")


if __name__ == "__main__":
    main()
