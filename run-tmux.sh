#!/bin/bash
# Visual tmux session for speckit-agents
# Opens panes for responder + worker pool with live output

SESSION="speckit"

# Default to 2 workers
WORKERS=${1:-2}

# Check if tmux is available
if ! command -v tmux &> /dev/null; then
    echo "tmux not found. Install with: brew install tmux"
    exit 1
fi

# Kill existing session if it exists
tmux kill-session -t "$SESSION" 2>/dev/null

# Create new session with responder in first pane (smaller)
tmux new-session -d -s "$SESSION" -n "responder"

# Split horizontally - top for responder, bottom for worker pool
tmux split-window -t "$SESSION" -v -p 30
tmux send-keys -t "$SESSION:responder" "cd /Users/sb/code/speckit-agents && source .venv/bin/activate && python responder.py" C-m

# Bottom pane - worker pool
tmux send-keys -t "$SESSION:responder" "cd /Users/sb/code/speckit-agents && source .venv/bin/activate && python worker_pool.py --workers $WORKERS" C-m

# Set status bar to show session info
tmux set-option -t "$SESSION" status-interval 5
tmux set-option -t "$SESSION" status-left "#[fg=green]speckit-agents#[default]"
tmux set-option -t "$SESSION" status-right "#[fg=yellow]Workers: $WORKERS#[default]"

# Attach to session
echo "Starting tmux session '$SESSION' with responder + $WORKERS workers..."
echo "Press Ctrl+B then D to detach, or Ctrl+C to kill session"
tmux attach-session -t "$SESSION"
