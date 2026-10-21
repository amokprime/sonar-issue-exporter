#!/bin/bash
# setup-sandbox.sh — sandbox-side, one-time-per-session script that copies
# project skills from the repo's skills/<name>/SKILL.md into the chat.z.ai
# sandbox's /home/z/my-project/skills/<name>/SKILL.md, so their `description`
# frontmatter auto-loads into the system prompt's `available_skills` list
# (invokable via `Skill(command="name")`).
#
# Run once at Onboard after cloning the repo; idempotent (re-running is a
# no-op — files are overwritten in place). Re-run if the sandbox resets.
#
# Usage: bash skills/delivery/scripts/setup-sandbox.sh
#
# Code quality per skills/code-quality/SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - Errors on stderr with explicit exit codes

set -euo pipefail

# Resolve repo root: the script lives at $REPO/skills/delivery/scripts/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SRC_SKILLS="$REPO/skills"
DEST_SKILLS="/home/z/my-project/skills"

if [[ ! -d "$SRC_SKILLS" ]]; then
  echo "ERROR: source skills dir not found: $SRC_SKILLS" >&2
  exit 1
fi

mkdir -p "$DEST_SKILLS"

# Copy every skills/<name>/SKILL.md (and any co-located scripts/ subfolder)
# into /home/z/my-project/skills/<name>/. Symlinks within skills/ (e.g.
# .omp/skills/<name>) are NOT followed — only the canonical SKILL.md and
# any sibling files.
copied=0
skipped=0
for skill_dir in "$SRC_SKILLS"/*/; do
  [[ -d "$skill_dir" ]] || continue
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$DEST_SKILLS/$skill_name"
  # Copy SKILL.md if present.
  if [[ -f "$skill_dir/SKILL.md" ]]; then
    cp -f "$skill_dir/SKILL.md" "$DEST_SKILLS/$skill_name/SKILL.md"
    copied=$((copied + 1))
  else
    skipped=$((skipped + 1))
    echo "skip (no SKILL.md): $skill_name" >&2
  fi
  # Copy co-located scripts/ if present (e.g. skills/delivery/scripts/).
  if [[ -d "$skill_dir/scripts" ]]; then
    rm -rf -- "${DEST_SKILLS:?}/$skill_name/scripts"
    cp -r "$skill_dir/scripts" "$DEST_SKILLS/$skill_name/scripts"
  fi
done

echo ""
echo "=== Setup Summary ==="
echo "Source:  $SRC_SKILLS"
echo "Dest:    $DEST_SKILLS"
echo "Copied:  $copied skill(s)"
echo "Skipped: $skipped (no SKILL.md)"

echo ""
echo "Now invoke skills via Skill(command=\"name\") instead of Read."
echo "Onboard-essential: Skill(command=\"sonar-issue-exporter\")"
echo "Domain skills: Skill(command=\"code-quality\"), Skill(command=\"sonarqube-workflow\"), Skill(command=\"skill\")"
