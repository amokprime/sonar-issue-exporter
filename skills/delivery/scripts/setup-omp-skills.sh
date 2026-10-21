#!/bin/bash
# setup-omp-skills.sh — creates the .omp/skills/<name> relative symlinks that
# point to ../../skills/<name>, so the OMP harness auto-loads the same
# skills as the chat.z.ai sandbox.
#
# The chat.z.ai sandbox blocks `ln -s` (defense-in-depth), so this script
# must be run locally after `unpack.sh` (or whenever a new skill is added to
# skills/). The script is idempotent — re-running detects existing valid
# symlinks and skips them; broken symlinks are replaced.
#
# Usage: bash skills/delivery/scripts/setup-omp-skills.sh
#
# Code quality per skills/code-quality/SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - Errors on stderr with explicit exit codes

set -euo pipefail

# Resolve repo root: the script lives at
# $REPO/skills/delivery/scripts/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SRC_SKILLS="$REPO/skills"
OMP_SKILLS="$REPO/.omp/skills"

mkdir -p "$OMP_SKILLS"

created=0
replaced=0
skipped=0

for skill_dir in "$SRC_SKILLS"/*/; do
  [[ -d "$skill_dir" ]] || continue
  skill_name="$(basename "$skill_dir")"
  link="$OMP_SKILLS/$skill_name"
  target="../../skills/$skill_name"

  # Skip if a valid symlink already points to the right target.
  if [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$target" ]]; then
    skipped=$((skipped + 1))
    continue
  fi

  # If a broken symlink or stale entry exists, remove it.
  if [[ -L "$link" ]] || [[ -e "$link" ]]; then
    rm -f -- "${link:?}"
    replaced=$((replaced + 1))
  fi

  ln -s "$target" "$link"
  created=$((created + 1))
done

echo ""
echo "=== OMP skills symlinks ==="
echo "Created:  $created"
echo "Replaced: $replaced"
echo "Skipped:  $skipped (already valid)"
echo ""
echo "Contents of $OMP_SKILLS/:"
ls -la "$OMP_SKILLS/"
