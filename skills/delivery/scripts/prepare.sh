#!/bin/bash
# prepare.sh — sandbox-side script that zips all deliverables in download/
# into a single deliver.zip, then removes the loose files.
#
# Usage: bash /home/z/my-project/skills/delivery/scripts/prepare.sh
#   (or wherever the sandbox-side copy lives — typically copied from
#    skills/delivery/scripts/prepare.sh at session start via setup-sandbox.sh)
#
# Output: /home/z/my-project/download/deliver.zip
#   (contains every loose file in download/ — flat, `__`-encoded names,
#    no subdirectories — PLUS deploy.sh which is one of those loose files)
#
# This script does five things:
#   1. Lint all *.md files in download/ (auto-fix bare #id/[id]/[[id]],
#      warn about overlong bullets -- see lint_markdown.py for details)
#   2. Verify deploy.sh exists in download/ (the directory-walking deploy
#      template — required for the user to run the deploy)
#   3. Run the shared lint gate (lint_gate.sh: Shellcheck + Ruff) on the
#      deliverables in download/ -- catches code quality failures BEFORE
#      zipping.
#   4. Syntax-check sie.py if present in download/ (catches the "empty
#      line 1 breaks shebang" class of bugs and other syntax errors
#      before zipping).
#   5. Zip everything into deliver.zip + clean up loose files + touch
#      download/ to refresh the chat.z.ai "All files in task" widget +
#      upload to tmpfiles.org as a widget-fallback URL.
#
# The linter + deploy.sh check + lint gate + syntax check are JIT reminders:
# if you forgot to copy deploy.sh, wrote bare #tokens in MEMORY.md, introduced
# a lint violation, or shipped a syntax-broken sie.py, this script fails
# before the zip is created. Fix the issues, then re-run.

set -euo pipefail

DOWNLOAD_DIR="/home/z/my-project/download"
ZIP="$DOWNLOAD_DIR/deliver.zip"
LINTER="/home/z/my-project/skills/delivery/scripts/lint_markdown.py"

# Source the shared lint gate (Shellcheck + Ruff).
# lint_gate.sh lives at skills/code-quality/scripts/ — owned by the code-quality skill.
LINT_GATE="/home/z/my-project/skills/code-quality/scripts/lint_gate.sh"
if [[ -f "$LINT_GATE" ]]; then
  # shellcheck disable=SC1090,SC1091 # dynamic path -- can't follow source at lint time
  . "$LINT_GATE"
fi

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
  echo "ERROR: download directory not found: $DOWNLOAD_DIR" >&2
  exit 1
fi

if [[ ! -f "$DOWNLOAD_DIR/deploy.sh" ]]; then
  echo "ERROR: deploy.sh not found in $DOWNLOAD_DIR — include it in the zip" >&2
  echo "  Copy the template from skills/delivery/scripts/deploy.sh to $DOWNLOAD_DIR/deploy.sh" >&2
  exit 1
fi

# ── Step 1: Lint markdown files ──────────────────────────────────────────────
echo "=== Linting markdown files ==="
md_files=()
while IFS= read -r f; do
  md_files+=("$f")
done < <(find "$DOWNLOAD_DIR" -maxdepth 1 -name '*.md' -type f | sort)

if [[ ${#md_files[@]} -gt 0 ]]; then
  python3 "$LINTER" "${md_files[@]}" || true
  # Linter exits 0 always (auto-fixes bare tokens, warns about overlong bullets).
  # The warning is the JIT reminder -- it doesn't block the zip.

  # ── STE-100 lint (advisory, non-blocking) ───────────────────────────────
  # Checks for STE structural rule violations (semicolons, long sentences,
  # phrasal verbs, nominalization, marketing adjectives, synonym rotation).
  # Advisory — prints findings but does NOT block the zip.
  STE_LINT="/home/z/my-project/skills/asd-ste100/scripts/ste-lint.py"
  if [[ -f "$STE_LINT" ]]; then
    echo ""
    echo "=== STE-100 lint (advisory) ==="
    python3 "$STE_LINT" --baseline 999 "${md_files[@]}" 2>&1 || true
    # --baseline 999: never fail the run (advisory only).
  fi
else
  echo "  (no .md files found -- skipping lint)"
fi

# ── Step 2: Run lint gate on deliverables in download/ ──────────────────────
# The gate runs Shellcheck on *.sh deliverables + Ruff on *.py deliverables.
# This is the consolidated gate call that catches code quality failures
# before zipping. The gate is blocking: if any installed linter finds
# issues after autofix, the script aborts before zipping.
echo ""
if type run_lint_gate >/dev/null 2>&1; then
  echo "=== Running lint gate on deliverables in download/ ==="
  if ! run_lint_gate "$DOWNLOAD_DIR"; then
    echo "ERROR: Lint gate failed on deliverables -- fix before zipping." >&2
    exit 1
  fi
else
  echo "  (skipped: lint_gate.sh not sourced -- run_lint_gate unavailable)"
  echo "  This means lint_gate.sh is missing from skills/code-quality/scripts/."
  echo "  Shellcheck + Ruff checks on deliverables were NOT run."
fi

# ── Step 3: Syntax-check sie.py if present ─────────────────────────────────
# A syntax error in sie.py means the entire script is broken. Catch it
# before zipping so the user doesn't ship a broken deliver.zip. The test
# suite imports sie as a module and doesn't catch all syntax errors (e.g.
# a missing shebang on line 1).
echo ""
echo "=== Syntax-checking sie.py ==="
if [[ -f "$DOWNLOAD_DIR/sie.py" ]]; then
  if ! python3 -c "import py_compile; py_compile.compile('$DOWNLOAD_DIR/sie.py', doraise=True)" 2>&1; then
    echo "ERROR: sie.py has a syntax error -- fix before zipping." >&2
    exit 1
  fi
  echo "  sie.py syntax OK."
else
  echo "  (no sie.py in download/ -- skipping syntax check)"
fi

# ── Step 4: Zip everything ──────────────────────────────────────────────────
echo ""
echo "=== Creating deliver.zip ==="

# Remove any previous zip
rm -f -- "$ZIP"

# Collect all loose files (exclude deliver.zip itself, subdirs, and known
# non-deliverable files that the chat.z.ai sandbox or the agent might leave
# in download/).
#
# Non-deliverable files skipped:
#   - README.md (the chat.z.ai sandbox default, 34 bytes: "Here are all
#     the generated files.") — would overwrite the real SIE README if zipped.
#     The real SIE README is ~11KB, so we skip any README.md < 100 bytes.
#   - REFACTOR-NOTES.md — a per-deliver meta-document for the user, not a
#     repo file.
#   - scratch.md — user notes, not a repo file.
cd "$DOWNLOAD_DIR"
mapfile -t files < <(find . -maxdepth 1 -type f ! -name 'deliver.zip' \
  ! -name 'REFACTOR-NOTES.md' ! -name 'scratch.md' | sort)

# Skip README.md only if it's the chat.z.ai default (small file). The real
# SIE README is ~11KB — if the agent ships a README.md change, it will be
# large and should be included.
filtered_files=()
for f in "${files[@]}"; do
  if [[ "$f" == "./README.md" ]]; then
    size=$(wc -c < "$f")
    if [[ "$size" -lt 100 ]]; then
      echo "  skip (chat.z.ai default README.md, $size bytes): $f"
      continue
    fi
  fi
  filtered_files+=("$f")
done
files=("${filtered_files[@]}")

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

# ── Touch download/ to refresh the chat.z.ai "All files in task" widget ─────
# The web UI's download widget can go stale after multiple prepare.sh runs or
# after sandbox-side file operations. Touching the directory's mtime forces
# the widget to re-scan and surface the new deliver.zip. If the widget is
# still broken, the tmpfiles.org upload (next step) provides a fallback URL.
touch -- "$DOWNLOAD_DIR"

# ── Step 5: Upload to tmpfiles.org as widget-fallback ──────────────────────
# The chat.z.ai "All files in task" widget has been flaky in some sessions --
# after prepare.sh runs, the widget doesn't surface the new deliver.zip and
# the user has no way to retrieve it. Uploading to tmpfiles.org gives the
# user a direct download URL printed in the chat that they can use as a
# fallback if the widget is broken.
#
# Only runs if all prior checks passed (lint + verify + lint gate + syntax
# check). Skipped silently if curl is unavailable or the upload fails -- the
# deliver.zip is still in $DOWNLOAD_DIR either way.
if command -v curl >/dev/null 2>&1 && [[ -f "$ZIP" ]]; then
  echo ""
  echo "=== Uploading deliver.zip to tmpfiles.org (widget fallback) ==="
  upload_response=$(curl -sS --max-time 60 -F "file=@$ZIP" https://tmpfiles.org/api/v1/upload 2>&1 || true)
  if [[ "$upload_response" =~ \"url\":\"([^\"]+)\" ]]; then
    page_url="${BASH_REMATCH[1]}"
    # The API returns a page URL like https://tmpfiles.org/<token>/deliver.zip.
    # The actual direct-download URL is on that page; fetch it.
    # --proto/--proto-redir "=https" pin the fetched page and any redirect it
    # issues to HTTPS (Sonar shell:S6506).
    dl_url=$(curl -sS --max-time 30 --proto "=https" --proto-redir "=https" \
      -L "$page_url" 2>/dev/null \
      | grep -oE 'https://tmpfiles\.org/dl/[^"]+' | head -n1 || true)
    if [[ -n "$dl_url" ]]; then
      echo "  Fallback URL: $dl_url"
      echo "  (paste in browser if the download widget is broken)"
    else
      echo "  Page URL: $page_url"
      echo "  (could not extract direct download URL -- visit the page to download)"
    fi
  else
    echo "  (upload failed -- curl output: $upload_response)"
    echo "  deliver.zip is still in $DOWNLOAD_DIR -- use the chat widget."
  fi
fi

# ── Clean up loose files ────────────────────────────────────────────────────
echo ""
echo "Cleaning up loose files..."
for f in "${files[@]}"; do
  rm -f -- "${DOWNLOAD_DIR:?}/${f#./}"
done

echo ""
echo "Done. download/ now contains only:"
ls -1 -- "$DOWNLOAD_DIR"
