#!/usr/bin/env bash
# One-time setup on the university GPU machine (Linux). No admin rights needed.
#
#   bash ml_research/scripts/uni_setup.sh            # CUDA torch matching nvidia-smi
#   bash ml_research/scripts/uni_setup.sh --cpu      # CPU torch (testing only)
# Extra options are passed to install_pinned.py, e.g. --cuda-tag cu132, or
#   --torch-version X --torchvision-version Y --cuda-tag cuNNN   (old driver; see the runbook)
#
# Installs uv for this user (if missing), Python 3.11 (managed by uv), a virtual environment in
# ml_research/.venv, the locked dependencies with CUDA torch, and the oscc_ml package.
set -euo pipefail

ML="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TORCH_ARGS=(--torch cuda)
PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu) TORCH_ARGS=(--torch cpu); shift ;;
    *) PASS+=("$1"); shift ;;
  esac
done

fail() { echo "SETUP FAILED: $1 -- FIX: $2" >&2; exit 1; }

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv for this user (no admin rights needed)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh \
    || fail "could not download uv" "check the internet connection or proxy (HTTPS_PROXY)"
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "uv is not on PATH" "open a new terminal and run this script again"

uv python install 3.11 || fail "could not install Python 3.11 with uv" "check the internet connection"
if [[ ! -x "$ML/.venv/bin/python" ]]; then
  uv venv --python 3.11 "$ML/.venv" || fail "could not create $ML/.venv" "check write access to $ML"
fi
PY="$ML/.venv/bin/python"

"$PY" "$ML/scripts/install_pinned.py" --python "$PY" --extra train "${TORCH_ARGS[@]}" "${PASS[@]}" \
  || fail "dependency installation failed (see the lines above)" \
          "fix the reported problem and run uni_setup again; it is safe to re-run"

if [[ "${TORCH_ARGS[1]}" == "cuda" ]]; then
  "$PY" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" \
    || fail "torch is installed but cannot see the GPU" "run nvidia-smi; update the NVIDIA driver if it fails"
fi

echo ""
echo "SETUP COMPLETE. Next: bash ml_research/scripts/uni_check.sh"
