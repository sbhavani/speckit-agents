#!/bin/bash
# Visual tmux session for speckit-agents with 3 panes
# Pane 1: Responder (listens for commands)
# Pane 2: Worker pool
# Pane 3: Optional - run orchestrator manually

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

# Create new session
tmux new-session -d -s "$SESSION" -n "main"

# Split into 3 vertical panes
# Top pane (responder) - 25% height
tmux split-window -t "$SESSION" -v -p 25

# Middle pane (worker pool) - 25% height
tmux split-window -t "$SESSION" -v -p 33

# Bottom pane - idle (for debugging/manual commands)

# Pane 1: Responder (top)
tmux send-keys -t "$SESSION:main.0" "cd /Users/sb/code/speckit-agents && source .venv/bin/activate && python responder.py" C-m

# Pane 2: Worker pool (middle)
tmux send-keys -t "$SESSION:main.1" "cd /Users/sb/code/speckit-agents && source .venv/bin/activate && python worker_pool.py --workers $WORKERS" C-m

# Pane 3: Helper text (bottom)
tmux send-keys -t "$SESSION:main.2" "echo 'Pane 3: Reserved for manual commands or orchestrator' && echo '' && echo 'Useful tmux commands:' && echo '  Ctrl+B then:' && echo '    D - detach' && echo '    0-2 - switch pane' && echo '    | - split horizontally' && echo '    - - split vertically'" C-m

# Select pane 0 (responder) to start
tmux select-pane -t "$SESSION:main.0"

# Set visual styling
tmux set-option -t "$SESSION" status-interval 5
tmux set-option -t "$SESSION" status-left "#[fg=green]● speckit#[default]"
tmux set-option -t "$SESSION" status-right "#[fg=yellow]$WORKERS workers#[default] | $(date +%H:%M)"

# Color pane borders
tmux set-option -t "$SESSION" pane-border-status top
tmux set-option -t "$SESSION" pane-border-format " #T "

echo "Starting tmux session '$SESSION'..."
echo ""
echo "Panes:"
echo "  1. Responder  (top)    - listens for @product-manager commands"
echo "  2. Worker pool (mid)   - $WORKERS workers processing features"
echo "  3. Manual     (bottom) - reserved for debugging"
echo ""
echo "Press Ctrl+B then D to detach, or Ctrl+C here to kill session"
echo ""

tmux attach-session -t "$SESSION"
