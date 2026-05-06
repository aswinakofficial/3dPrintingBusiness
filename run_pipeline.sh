#!/bin/bash
# Rebuilds the TRELLIS image in ACR (cloud-side, no local Docker needed),
# then submits an ACI job and tails the cloud logs to /tmp/pipeline_run.log.
#
# Run from the repo root. Safe to leave running unattended.

set -uo pipefail

LOG=/tmp/pipeline_run.log
REPO_ROOT="/home/aswinak/Projects/3dPrintingBusiness"
ACR_NAME="${AZURE_CONTAINER_REGISTRY_NAME:-acr3dfigurinelabdev}"
INPUT_DIR="${1:-$REPO_ROOT/input/Paramu/}"

cd "$REPO_ROOT"

{
  echo "==================================================="
  echo " 3D Figurine Pipeline Run — $(date)"
  echo "==================================================="

  echo ""
  echo "[1/2] Building TRELLIS image in ACR (~2-10 min, mostly cached)..."
  az acr build \
    --registry "$ACR_NAME" \
    --image 3dfigurine-trellis:latest \
    -f docker/Dockerfile.trellis . \
    || { echo "ACR build failed"; exit 1; }

  echo ""
  echo "[2/2] Submitting ACI job and streaming progress..."
  python3 scripts/run_job.py \
    --engine trellis \
    --input "$INPUT_DIR" \
    --cleanup
  JOB_EXIT=$?

  echo ""
  echo "==================================================="
  echo " Job exit code: $JOB_EXIT"
  if [ "$JOB_EXIT" -eq 0 ]; then
    echo " RESULT: Output STL is in $REPO_ROOT/output/"
    ls -la "$REPO_ROOT/output/" 2>/dev/null | head -20
  else
    echo " RESULT: Pipeline FAILED — see logs above"
  fi
  echo "==================================================="
  echo " DONE — $(date)"
  echo "==================================================="
} 2>&1 | tee "$LOG"
