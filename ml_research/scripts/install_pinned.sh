#!/usr/bin/env bash
# Install oscc-ml with the exact versions from uv.lock, choosing how torch is provided.
#
# Every package except the torch family (torch, torchvision, triton, nvidia-*) is installed at
# its locked version. The torch family depends on the platform:
#
#   --torch cpu       CPU wheels of the LOCKED torch/torchvision versions from the PyTorch CPU
#                     index (CI and laptops). Keeps CI small and offline-capable after caching.
#   --torch platform  Keep the torch already installed (Colab/Kaggle CUDA builds). Fails if
#                     torch is missing. Its version is recorded in every run's environment.json.
#   --torch locked    The locked versions from PyPI (Linux: CUDA build, e.g. the lab GPU).
#
# Usage (from anywhere):
#   bash ml_research/scripts/install_pinned.sh --torch cpu --extra train --dev
#   bash ml_research/scripts/install_pinned.sh --torch platform --extra train     # Colab/Kaggle
#
# Needs `uv` (for `uv export`). Installs into the active virtualenv with `uv pip`, or into the
# current interpreter with `python -m pip` when no virtualenv is active (Colab/Kaggle).
set -euo pipefail

TORCH_MODE=cpu
EXTRAS=()
WITH_DEV=0
CPU_INDEX="https://download.pytorch.org/whl/cpu"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --torch) TORCH_MODE="$2"; shift 2 ;;
    --extra) EXTRAS+=("$2"); shift 2 ;;
    --dev) WITH_DEV=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$TORCH_MODE" in cpu|platform|locked) ;; *) echo "--torch must be cpu|platform|locked" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PIP=(uv pip install)
  PY="$VIRTUAL_ENV/bin/python"
  [[ -x "$PY" ]] || PY="$VIRTUAL_ENV/Scripts/python.exe"
else
  PY="$(command -v python3 || command -v python)"
  PIP=("$PY" -m pip install)
fi

export_args=(--frozen --no-hashes --no-annotate --no-header --no-emit-project --format requirements.txt)
for extra in "${EXTRAS[@]}"; do export_args+=(--extra "$extra"); done
if [[ "$WITH_DEV" == 1 ]]; then export_args+=(--group dev); else export_args+=(--no-dev); fi

(cd "$ROOT" && uv export "${export_args[@]}") > "$TMP/all.txt"

TORCH_FAMILY='^(torch|torchvision|triton|pytorch-triton|nvidia-[a-z0-9-]+)=='
grep -viE "$TORCH_FAMILY" "$TMP/all.txt" > "$TMP/rest.txt" || true

locked_version() { grep -E "^$1==" "$TMP/all.txt" | head -n1 | sed -E "s/^$1==([^ ;]+).*/\1/"; }
TORCH_VERSION="$(locked_version torch || true)"
TV_VERSION="$(locked_version torchvision || true)"

if [[ -n "$TORCH_VERSION" ]]; then
  case "$TORCH_MODE" in
    cpu)
      echo "Installing CPU torch==$TORCH_VERSION torchvision==$TV_VERSION from $CPU_INDEX"
      # --no-deps: torch's own dependencies are pinned in rest.txt.
      "${PIP[@]}" --no-deps --index-url "$CPU_INDEX" "torch==$TORCH_VERSION" "torchvision==$TV_VERSION"
      ;;
    platform)
      "$PY" -c "import torch, torchvision; print('Using platform torch', torch.__version__, 'CUDA', torch.version.cuda)" \
        || { echo "--torch platform: torch is not installed in this interpreter" >&2; exit 1; }
      ;;
    locked)
      grep -iE "$TORCH_FAMILY" "$TMP/all.txt" > "$TMP/torch.txt"
      "${PIP[@]}" -r "$TMP/torch.txt"
      ;;
  esac
fi

# The exported set is complete and pinned, so dependency resolution is unnecessary.
"${PIP[@]}" --no-deps -r "$TMP/rest.txt"
"${PIP[@]}" --no-deps -e "$ROOT"
"$PY" -c "import oscc_ml; print('oscc_ml', oscc_ml.__version__, 'installed')"
