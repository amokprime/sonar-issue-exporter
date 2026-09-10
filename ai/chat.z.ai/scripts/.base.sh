#!/bin/bash
# .base.sh — sourced by each upload workflow script (repomix.sh, zip.sh),
# which must define snippet() first.
#
# Mirrors LineByLine's ai/chat.z.ai/scripts/.base.sh pattern: the shared
# setup (path resolution, scratch/upload dir, zip+clipboard) lives here;
# the workflow script defines snippet() with the workflow-specific command
# (repomix invocation for repomix.sh, empty-guard for zip.sh).
#
# Code quality per code-quality-SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail (fail fast — abort before deleting anything or
#     copying a stale path to clipboard)
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - SONAR_ISSUE_EXPORTER_ROOT override (config over constants)
#   - Errors on stderr with explicit exit codes

set -euo pipefail

root="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
scratch="$root/scratch"
upload="$scratch/upload"
unique="$(date +%s%N).zip"

# repomix is installed via `npm install -g repomix` → ~/.npm-global/bin by
# default. Add that to PATH first, then fall back to the rest of PATH.
export PATH="$HOME/.npm-global/bin:$PATH"

# Require the caller to define snippet() before sourcing us.
type snippet >/dev/null 2>&1 || {
  echo "snippet() not defined by caller" >&2
  exit 1
}

# ── Sanity checks ────────────────────────────────────────────────────────────
if [[ ! -d "$root" ]]; then
  echo "ERROR: repo root not found: $root" >&2
  echo "Set SONAR_ISSUE_EXPORTER_ROOT or clone to ~/GitHub/sonar-issue-exporter" >&2
  exit 1
fi

# Clear stale upload zips from scratch/ so the next run starts fresh.
rm -f "${scratch:?}"/scratch/*.zip 2>/dev/null || true
rm -f "${scratch:?}"/*.zip 2>/dev/null || true

mkdir -p "$upload"
cd "$root" || exit 1

# ── Run the workflow-specific snippet ────────────────────────────────────────
# snippet() is responsible for populating $upload/ with the files to zip
# (repomix output for repomix.sh, user-staged files for zip.sh).
snippet

# ── Zip + clipboard ──────────────────────────────────────────────────────────
cd "$upload" || exit 1
zip -r "../$unique" ./*
rm -rf "${upload:?}"/*

# Clipboard: Wayland wl-copy first, then X11 xclip, then macOS pbcopy.
if command -v wl-copy >/dev/null 2>&1; then
  wl-copy "$scratch/$unique" || echo "warning: wl-copy failed; zip is at $scratch/$unique" >&2
elif command -v xclip >/dev/null 2>&1; then
  echo -n "$scratch/$unique" | xclip -selection clipboard
elif command -v pbcopy >/dev/null 2>&1; then
  echo -n "$scratch/$unique" | pbcopy
else
  echo "warning: no clipboard tool found (wl-copy/xclip/pbcopy)" >&2
  echo "zip is at: $scratch/$unique" >&2
fi

echo "Done. Zip: $scratch/$unique (path copied to clipboard)"
