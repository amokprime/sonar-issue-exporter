#!/bin/bash
# prepare.sh — sandbox-side script that zips all deliverables in download/
# into a single deliver.zip, then removes the loose files.
#
# Usage: bash /home/z/my-project/scripts/prepare.sh
#
# Output: /home/z/my-project/download/deliver.zip
#   (contains every loose file in download/ — flat, hyphenated names,
#    no subdirectories — PLUS deploy.sh which is one of those loose files)
#
# After zipping, the loose files are removed so only deliver.zip remains.
# This enforces the "keep download/ clean between turns" rule: the same
# file should not exist both inside and outside the zip.
#
# The user's `dsie` fish abbreviation runs ai/chat.z.ai/scripts/delivery/unpack.sh
# which extracts deliver.zip, runs deploy.sh, and cleans up.
#
# Code quality per code-quality-SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - Arrays via mapfile instead of word-splitting
#   - Errors on stderr with explicit exit codes

set -euo pipefail

DOWNLOAD_DIR="/home/z/my-project/download"
ZIP="$DOWNLOAD_DIR/deliver.zip"

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
  echo "ERROR: download directory not found: $DOWNLOAD_DIR" >&2
  exit 1
fi

if [[ ! -f "$DOWNLOAD_DIR/deploy.sh" ]]; then
  echo "ERROR: deploy.sh not found in $DOWNLOAD_DIR — create it first" >&2
  exit 1
fi

# Remove any previous zip
rm -f -- "$ZIP"

# Collect all loose files (exclude deliver.zip itself and any subdirs).
# mapfile avoids word-splitting issues (SC2086) — filenames with spaces
# would break a bare `for f in $files` loop, though we enforce hyphenated
# names so this is defense-in-depth.
cd "$DOWNLOAD_DIR"
mapfile -t files < <(find . -maxdepth 1 -type f ! -name 'deliver.zip' | sort)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "ERROR: no files to zip in $DOWNLOAD_DIR" >&2
  exit 1
fi

# Zip everything (flat, no subdirectories). -j = junk paths, -q = quiet.
zip -jq "$ZIP" "${files[@]}"

echo "Created $ZIP"
echo ""
echo "Contents:"
unzip -l "$ZIP" | tail -n +4 | head -n -2

# ── Clean up loose files ────────────────────────────────────────────────────
# Only deliver.zip should remain in download/. This enforces the
# "keep download/ clean between turns" rule.
echo ""
echo "Cleaning up loose files..."
for f in "${files[@]}"; do
  # $f is like "./filename" — strip the leading ./
  # ${DOWNLOAD_DIR:?} guard prevents rm from targeting root if the var is unset (SC2115).
  rm -f -- "${DOWNLOAD_DIR:?}/${f#./}"
done

echo ""
echo "Done. download/ now contains only:"
ls -1 -- "$DOWNLOAD_DIR"