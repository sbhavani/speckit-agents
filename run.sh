#!/bin/bash
# Run speckit-agents: responder + worker pool
# Usage: ./run.sh [num_workers]

WORKERS=${1:-2}

echo "Starting worker pool with $WORKERS workers..."
uv run python worker_pool.py --workers $WORKERS &
WORKER_PID=$!

echo "Starting responder..."
uv run python responder.py &
RESPONDER_PID=$!

echo "Running!"
echo "Worker pool PID: $WORKER_PID"
echo "Responder PID: $RESPONDER_PID"
echo ""
echo "Press Ctrl+C to stop both"

# Wait for either to exit
wait $WORKER_PID $RESPONDER_PID
