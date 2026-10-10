#!/usr/bin/env bash
# Starts the runner for one job. The slot on the VM (scripts/runner-vm/
# dx-runner-slot.sh) asks GitHub for a just-in-time configuration and passes it
# in DX_JIT_CONFIG: a runner registered that way takes exactly one job and is
# removed from GitHub when it ends, so the container exits and is discarded.
set -euo pipefail
if [ -z "${DX_JIT_CONFIG:-}" ]; then
  echo "dx-runner: DX_JIT_CONFIG is empty; run this image through dx-runner-slot.sh" >&2
  exit 64
fi
cd /home/runner/actions-runner
exec ./run.sh --jitconfig "$DX_JIT_CONFIG"
