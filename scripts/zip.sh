#!/bin/bash
# zip.sh — ad-hoc zip utility for the sonar-issue-exporter repo's
# scratch/upload/ folder.
#
# Zips whatever is in $SONAR_ISSUE_EXPORTER_ROOT/scratch/upload/ into a
# uniquely-named zip in scratch/, then copies the path to clipboard via
# wl-copy (with xclip/pbcopy fallbacks). Aborts with an error if the
# upload folder is empty. Used for ad-hoc uploads of non-deliverable
# files (e.g. a single screenshot or test fixture).
#
# Can be double-clicked after setup. Manual deployment only — must be
# copied to the user's scripts/ folder outside the deliver.zip workflow.
#
# Usage:
#   1. Stage files in ~/GitHub/sonar-issue-exporter/scratch/upload/
#   2. Run ./zip.sh
#   3. Paste the clipboard path into the chat.z.ai file picker
#
# Code quality per skills/code-quality/SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - SONAR_ISSUE_EXPORTER_ROOT override (config over constants)
#   - Errors on stderr with explicit exit codes

set -euo pipefail

root="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
scratch="$root/scratch"
upload="$scratch/upload"
unique="$(date +%s%N).zip"

export PATH="$HOME/.npm-global/bin:$PATH"

# Abort if upload folder is missing or empty (would otherwise produce an
# empty zip or fail with a confusing error).
if [[ ! -d "$upload" ]]; then
  echo "ERROR: upload folder not found: $upload" >&2
  exit 1
fi
if [[ -z "$(ls -A "$upload")" ]]; then
  echo "Nothing to zip: $upload is empty" >&2
  exit 1
fi

mkdir -p "$upload"
cd "$root" || exit 1

# Zip the upload folder contents into scratch/$unique.
cd "$upload" || exit 1
zip -r "../$unique" ./*
rm -rf "${upload:?}"/*

# Clean up stale zips in $scratch/: remove any *.zip that is at least
# 1 hour older than the just-generated $unique. Sweeps old zips from prior
# double-click runs while keeping recent ones (e.g. rapid successive runs
# within the same session). The threshold is relative to "now" (effectively
# the same as "relative to $unique" since $unique was created seconds ago).
removed=$(find "${scratch:?}" -maxdepth 1 -name '*.zip' -type f \
  ! -name "$unique" \
  -mmin +60 \
  -print -delete)
if [[ -n "$removed" ]]; then
  echo "Removed stale zip(s) older than 1 hour:"
  # Prefix each line with two spaces for readability. Parameter expansion
  # avoids sed (shellcheck SC2001): ${var//search/replace} does global replace.
  printf '  %s\n' "${removed//$'\n'/$'\n'  }"
fi

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

notify-send "Zip created" "$scratch/$unique"
