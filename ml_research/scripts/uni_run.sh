#!/usr/bin/env bash
# Full pipeline on the university GPU machine (Linux):
#   prepare -> sweep -> train-all -> evaluate -> report -> pack-results
# Every step is skipped when already complete, so running this again after a crash or reboot
# continues where it stopped. Full log with tracebacks: ml_research/runs/uni_run.log
#
#   bash ml_research/scripts/uni_run.sh ml_research/data/raw/kaggle_kebede/archive.zip   # background (tmux or nohup)
#   bash ml_research/scripts/uni_run.sh <zip or extracted folder> --foreground   # in this terminal
# Further options are passed to `oscc-ml uni-run` (see `oscc-ml uni-run --help`).
set -euo pipefail

ML="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OSCC="$ML/.venv/bin/oscc-ml"
LOG="$ML/runs/uni_run.log"

if [[ $# -lt 1 ]]; then
  echo "usage: bash ml_research/scripts/uni_run.sh <path to the Kaggle zip or extracted folder> [--foreground] [options]" >&2
  exit 2
fi
RAW="$1"; shift
FOREGROUND=0
PASS=()
for arg in "$@"; do
  if [[ "$arg" == "--foreground" ]]; then FOREGROUND=1; else PASS+=("$arg"); fi
done

[[ -x "$OSCC" ]] || { echo "RUN FAILED: ml_research/.venv missing -- FIX: run scripts/uni_setup.sh first" >&2; exit 1; }
[[ -e "$RAW" ]] || { echo "RUN FAILED: $RAW not found -- FIX: give the full path to the Kaggle zip or extracted folder" >&2; exit 1; }
RAW="$(cd "$(dirname "$RAW")" && pwd)/$(basename "$RAW")"
mkdir -p "$ML/runs"

CMD=("$OSCC" uni-run --raw "$RAW" "${PASS[@]}")
if [[ "$FOREGROUND" == 1 ]]; then
  exec "${CMD[@]}"
fi

if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t oscc 2>/dev/null; then
    echo "A tmux session 'oscc' already exists. Attach with: tmux attach -t oscc" >&2
    exit 1
  fi
  printf -v QUOTED '%q ' "${CMD[@]}"
  tmux new-session -d -s oscc "$QUOTED; echo; echo 'uni_run finished. Press Enter to close.'; read -r _"
  echo "Started in tmux session 'oscc'."
  echo "  watch it:   tmux attach -t oscc     (detach again with Ctrl+B then D)"
else
  nohup "${CMD[@]}" > "$ML/runs/uni_run.console.log" 2>&1 &
  echo "Started in the background with nohup (PID $!); it keeps running after you log out."
  echo "  console output: $ML/runs/uni_run.console.log"
fi
echo "  progress log:  tail -f $LOG"
