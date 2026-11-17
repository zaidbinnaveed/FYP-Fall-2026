#!/usr/bin/env bash
# Thin wrapper kept for CI and the Colab/Kaggle notebook; the logic lives in install_pinned.py
# (standard library only, works on Windows and Linux). Options are passed through, e.g.
#   VIRTUAL_ENV=.venv bash scripts/install_pinned.sh --torch cpu --extra train --dev
#   bash scripts/install_pinned.sh --torch platform --extra train          # Colab/Kaggle
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
  [[ -x "$PY" ]] || PY="$VIRTUAL_ENV/Scripts/python.exe"
else
  PY="$(command -v python3 || command -v python)"
fi

exec "$PY" "$HERE/install_pinned.py" --python "$PY" "$@"
