#!/bin/bash
# diff-main.sh — capture the local working tree state (uncommitted + untracked
# + unpushed commits) as a portable patch + metadata so an AI agent in another
# sandbox can reproduce the local state by cloning the main branch and applying
# the patch.
#
# Output goes to $REPO/scratch/upload/:
#   changes.patch  — `git diff --binary $BASE_SHA` covering tracked + untracked
#   changes.status  — `git status --porcelain` (the authoritative pre-mutation state)
#   changes.meta    — base_ref, base_sha, head_sha, branch, status_file pointer
#
# Usage: bash scripts/diff-main.sh
#
# This project pushes directly to `main` (no staging branch), so the diff is
# against origin/main.
set -euo pipefail

REPO="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
OUT="$REPO/scratch/upload"
mkdir -p "$OUT"

g() { git -C "$REPO" "$@"; }

NEWFILES=$(mktemp)
POST=$(mktemp)

reset_ita() {
  # xargs can't invoke bash functions (SC2032/SC2033) — call git directly
  # with the -C flag instead of the g() wrapper. Use if/then (SC2015) rather
  # than `[ ... ] && cmd || true` so the `|| true` only applies to the xargs
  # call, not to the test.
  if [[ -s "$NEWFILES" ]]; then
    xargs -0 -r git -C "$REPO" reset -q -- < "$NEWFILES" || true
  fi
  : > "$NEWFILES"
}
trap 'reset_ita; rm -f "$NEWFILES" "$POST"' EXIT INT TERM

g fetch origin main
BASE_SHA=$(g rev-parse origin/main)

#### authoritative pre-mutation state — this is what the agent should match
g status --porcelain > "$OUT/changes.status"
g ls-files --others --exclude-standard -z > "$NEWFILES"

g add -N .
g --no-pager diff --binary "$BASE_SHA" > "$OUT/changes.patch"
reset_ita

#### sanity: should be identical to the pre-mutation capture
g status --porcelain > "$POST"

{
  echo "base_ref:    origin/main"
  echo "base_sha:    $BASE_SHA"
  echo "head_sha:    $(g rev-parse HEAD)"
  echo "branch:      $(g rev-parse --abbrev-ref HEAD)"
  echo "status_file: changes.status"
  if ! diff -q "$OUT/changes.status" "$POST" >/dev/null; then
    echo
    echo "post_reset_status_diff:"
    diff "$OUT/changes.status" "$POST" || true
  fi
} > "$OUT/changes.meta"

notify-send "Main diff updated."
