#!/bin/bash
# unpack.sh — user-side deployment script for sonar-issue-exporter.
# Run via the `dsie` fish abbreviation
# (abbr --add dsie '~/GitHub/sonar-issue-exporter/ai/chat.z.ai/scripts/delivery/unpack.sh')
# from a terminal (NOT double-clicked) so output is visible.
#
# Extracts deliver.zip to scratch/, runs deploy.sh (which deploys files,
# installs sie.py, cleans up 0.2.x artifacts, runs uv sync + ruff + pytest,
# then cleans up only the zip-extracted files), then removes deploy.sh +
# deliver.zip.
#
# Code quality per code-quality-SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - SONAR_ISSUE_EXPORTER_ROOT override (config over constants)
#   - unzip -oqq — -o overwrites stale files from a failed previous run
#   - INT/TERM trap cleans up deploy.sh + deliver.zip on Ctrl+C
#   - Errors on stderr with explicit exit codes

set -euo pipefail

DEST="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
SCRATCH="$DEST/scratch"
DELIVER_ZIP="$SCRATCH/deliver.zip"
DEPLOY_SH="$SCRATCH/deploy.sh"
DELIVER_LIST="$SCRATCH/.deliver-files.list"

# ── Signal-trap cleanup ──────────────────────────────────────────────────────
# Ctrl+C during the test step leaves deploy.sh, deliver.zip, and
# .deliver-files.list in scratch/, requiring manual cleanup. The trap fires
# only on INT/TERM — set -e failures leave files for debugging (next run's
# `unzip -oqq` overwrites anyway).
cleanup() {
  rm -f -- "${DEPLOY_SH:?}" "${DELIVER_ZIP:?}" "${DELIVER_LIST:?}"
  echo "" >&2
  echo "Cleaned up deploy.sh + deliver.zip + .deliver-files.list (Ctrl+C caught)." >&2
}
trap cleanup INT TERM

# ── Sanity checks ────────────────────────────────────────────────────────────
if [[ ! -d "$SCRATCH" ]]; then
  echo "ERROR: scratch dir not found: $SCRATCH" >&2
  exit 1
fi
if [[ ! -f "$DELIVER_ZIP" ]]; then
  echo "ERROR: deliver.zip not found at $DELIVER_ZIP" >&2
  echo "Download deliver.zip from the chat first." >&2
  exit 1
fi

cd "$SCRATCH"

# Snapshot the zip's contents before extraction so deploy.sh can clean up
# ONLY the files that came from the zip (plus deliver.zip and deploy.sh).
# This protects pre-existing files in scratch/ (e.g. scratch.md notes,
# prior session's upload zips) from being swept by the cleanup phase.
# Writes one filename per line to .deliver-files.list (hidden dotfile so
# it doesn't collide with any real deliverable).
unzip -l "$DELIVER_ZIP" | awk 'NR>3 && $4 != "" {print $4}' > "$DELIVER_LIST"

# Extract (-o overwrites stale files from a failed previous run; -qq = quiet).
unzip -oqq "$DELIVER_ZIP"

# Run deploy.sh (deploys files, installs sie.py, cleans up 0.2.x artifacts,
# runs uv sync + ruff + pytest, then cleans up only the zip-extracted files).
chmod +x "$DEPLOY_SH"
./deploy.sh

# ── Normal-exit cleanup ─────────────────────────────────────────────────────
# Disable the signal trap so Ctrl+C during the final rm doesn't recurse.
trap - INT TERM
cleanup
