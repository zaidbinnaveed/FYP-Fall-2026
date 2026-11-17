#!/usr/bin/env bash
# Readiness check on the university GPU machine (Linux): Python, GPU name and VRAM, free disk,
# write access, pretrained-weight downloads, then a ~2-minute GPU smoke run of all four models.
# Output is also saved to ml_research/runs/uni_check.log (send that file if something fails).
#
#   bash ml_research/scripts/uni_check.sh
# Options are passed to `oscc-ml check` (e.g. --allow-cpu --skip-download for CI).
set -uo pipefail

ML="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OSCC="$ML/.venv/bin/oscc-ml"
if [[ ! -x "$OSCC" ]]; then
  echo "CHECK FAILED: ml_research/.venv is missing or incomplete -- FIX: run bash ml_research/scripts/uni_setup.sh first"
  exit 1
fi
mkdir -p "$ML/runs"
"$OSCC" check "$@" 2>&1 | tee "$ML/runs/uni_check.log"
exit "${PIPESTATUS[0]}"
