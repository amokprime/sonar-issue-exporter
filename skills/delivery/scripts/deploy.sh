#!/bin/bash
# deploy.sh — deploys session files from cwd (where deliver.zip was extracted)
# to the sonar-issue-exporter repo, then cleans up 0.2.x artifacts and runs
# the lint gate + SonarCloud exclusion-coverage check + test suite.
#
# Called by scripts/unpack.sh after extraction. This file is committed at
# skills/delivery/scripts/deploy.sh as a template — each session, the agent
# includes this template inside deliver.zip unchanged. The agent doesn't
# fill in `deploy_file` mappings; instead, the script walks every file in
# cwd and derives the repo-relative path from each flat filename.
#
# Path encoding (the `__` separator):
#   Files in deliver.zip use `__` (double underscore) as the path separator.
#   Single hyphens in real filenames (e.g. `code-quality`, `input-forms`,
#   `sonar-issue-exporter`) are preserved literally — `__` is unambiguous
#   because no real filename or directory name in this project uses `__`.
#   To decode: replace `__` with `/` to get the repo-relative path.
#   Files with no `__` in their name (e.g. `sie.py`, `AGENTS.md`, `.gitignore`)
#   are deployed to the repo root.
#
#   Examples:
#     sie.py                                  → sie.py
#     AGENTS.md                               → AGENTS.md
#     .gitignore                              → .gitignore
#     docs__input-forms.md                    → docs/input-forms.md
#     tests__test_url_parsing.py              → tests/test_url_parsing.py
#     skills__code-quality__SKILL.md          → skills/code-quality/SKILL.md
#     scripts__espanso.yml                    → scripts/espanso.yml
#     .omp__config.yml                        → .omp/config.yml
#
# Output is streamed live to the terminal. A filtered log (errors + summaries)
# is written to scratch/upload/deploy.log for the user to review after the
# deploy if the terminal output scrolled past.
#
# Lint gate + test failures do NOT abort the script — the log is always
# printed and cleanup always runs. Only deploy_file + uv sync failures
# abort early (those indicate a broken delivery, not a test regression).

set -euo pipefail

DEST="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
SCRATCH="$DEST/scratch"
SIE_BIN="${XDG_BIN_HOME:-$HOME/.local/bin}/sie"

# ── Logging ─────────────────────────────────────────────────────────────────
# A filtered log (errors + summary lines) is written to scratch/upload/deploy.log
# so the user can review it after the deploy. The raw output is teed to a
# temp file, filtered into the log, then the temp is cleaned up on exit.
LOG="$SCRATCH/upload/deploy.log"
RAW="$SCRATCH/upload/deploy.raw.tmp"

mkdir -p "$(dirname "$LOG")"
: > "$LOG"
: > "$RAW"

# log_section: print a header to both terminal and log
log_section() {
  echo ""
  echo "=== $1 ==="
  echo "" >> "$LOG"
  echo "=== $1 ===" >> "$LOG"
}

# log_filter: extract errors + summary lines from $RAW, append to $LOG, reset $RAW
log_filter() {
  # Filter: errors, failures, warnings, summaries, deploy results.
  # NOT included: "passed" (would log every individual test PASSED line).
  # The pytest summary line "182 passed in 0.81s" is matched by "passed in".
  grep -iE "error|fail|warn|skipped|gate|exit [1-9]|removed|deployed|changed|Tests +[0-9]|passed in|Cognitive Complexity|ruff|shellcheck|no such file|not found|cannot|could not|unable|EROFS|read-only|manual deploy" "$RAW" >> "$LOG" 2>/dev/null || true
  : > "$RAW"
}

# run_and_log: run a command, tee output to $RAW, then filter into $LOG.
# Does NOT abort on non-zero exit (test/lint failures are expected — we want
# the full log regardless so the user can review the output after the deploy).
run_and_log() {
  "$@" 2>&1 | tee "$RAW" || true
  log_filter
}

# ── EXIT trap: clean up $RAW, print exit code ────────────────────────────────
# Always runs — success, set -e failure, INT/TERM signal. Captures the exit
# code so the user sees whether the deploy succeeded. The filtered log is
# saved to scratch/upload/deploy.log (NOT cleaned up — the user reviews it).
cleanup() {
  local exit_code=$?
  rm -f -- "${RAW:?}" 2>/dev/null || true
  echo ""
  echo "  Done. (exit $exit_code)"
  echo "  Deploy log saved to: $LOG"
  echo "" >> "$LOG"
  echo "  Done. (exit $exit_code)" >> "$LOG"
  exit "$exit_code"
}
trap cleanup EXIT

# ── Source the shared lint gate ───────────────────────────────────────────────
# Prefer the zip's extracted copy in scratch/ (always current this session)
# over the repo's copy (may be stale from a previous deploy — the
# chicken-and-egg problem: deploy.sh sources lint_gate.sh BEFORE deploy_file
# updates it, so the FIRST run after a lint_gate.sh change uses the OLD
# version. Sourcing from scratch/ avoids this: the zip's copy is always the
# latest.)
LINT_GATE_SCRATCH="$SCRATCH/skills__code-quality__scripts__lint_gate.sh"
LINT_GATE_REPO="$DEST/skills/code-quality/scripts/lint_gate.sh"
if [[ -f "$LINT_GATE_SCRATCH" ]]; then
  # shellcheck disable=SC1090,SC1091
  . "$LINT_GATE_SCRATCH"
elif [[ -f "$LINT_GATE_REPO" ]]; then
  # shellcheck disable=SC1090,SC1091
  . "$LINT_GATE_REPO"
else
  echo "WARN: lint_gate.sh not found — skipping shared lint gate" >&2
fi

# ── Non-deliverable files to skip ────────────────────────────────────────────
# These are files that might be in scratch/ alongside deliver.zip but should
# NOT be deployed to the repo. They are LEFT in scratch/ (not deleted) —
# the user's scratch/ files are preserved.
#
# Non-deliverable files skipped (left in scratch/):
#   - README.md (the chat.z.ai sandbox default, 34 bytes) — would overwrite
#     the real SIE README. The real SIE README is ~11KB, so we skip any
#     README.md < 100 bytes.
#   - REFACTOR-NOTES.md — a per-deliver meta-document for the user.
#   - scratch.md — user notes.
#   - *.zip — any zip files in scratch/ (upload zips, prior deliver.zip, etc.)
#     are NOT deployable files and must not be moved to the repo.
non_deliverable=(README.md REFACTOR-NOTES.md scratch.md)

# Files unpack.sh owns — skip these when walking cwd.
unpack_owned=(deploy.sh deliver.zip .deliver-files.list)

# Arrays for the summary — collect results as we go.
changed=()
skipped_identical=()
skipped_owned=()
skipped_non_deliverable=()
manual_deploys=()

# is_in_list <filename> <array_name> — true if filename is in the named array
is_in_list() {
  local f="$1"
  shift
  local item
  for item in "$@"; do
    [[ "$f" == "$item" ]] && return 0
  done
  return 1
}

# decode_path <flat_filename> — print the repo-relative path by replacing
# `__` with `/`. Files with no `__` print the filename unchanged (deploy
# to repo root).
decode_path() {
  local flat="$1"
  printf '%s' "${flat//__//}"
}

# deploy_file <flat_filename>
# Decodes the path, moves the file if it differs from the destination,
# skips if byte-identical. Handles EROFS (read-only filesystem) inside
# the bwrap sandbox — files targeting read-only paths (e.g. scripts/unpack.sh,
# .git/, archive/) are added to manual_deploys instead of aborting.
deploy_file() {
  local src="$1"
  local rel
  rel=$(decode_path "$src")
  local dst="$DEST/$rel"

  if [[ ! -f "$src" ]]; then
    return 0
  fi

  if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
    skipped_identical+=("$rel")
    rm -- "${src:?}"
  else
    mkdir -p "$(dirname "$dst")" 2>/dev/null || true
    if mv -- "$src" "$dst" 2>/dev/null; then
      changed+=("$rel")
      echo "deployed: $rel" >> "$LOG"
    else
      manual_deploys+=("$rel")
      echo "MANUAL DEPLOY: $rel (read-only destination)" >> "$LOG"
    fi
  fi
}

# ── Walk every file in cwd ───────────────────────────────────────────────────
# Use find with -maxdepth 1 so we don't recurse (deliver.zip is flat).
# Exclude ALL *.zip files (not just deliver.zip) — upload zips, prior
# deliver.zip copies, and any other zips in scratch/ are NOT deployable.
# Skip: unpack_owned files (deploy.sh, deliver.zip, .deliver-files.list),
# non_deliverable files (README.md, REFACTOR-NOTES.md, scratch.md).
mapfile -t all_files < <(find . -maxdepth 1 -type f ! -name '*.zip' | sort)

for f in "${all_files[@]}"; do
  flat="${f#./}"
  if is_in_list "$flat" "${unpack_owned[@]}"; then
    skipped_owned+=("$flat")
    continue
  fi
  if is_in_list "$flat" "${non_deliverable[@]}"; then
    # Check if README.md is the chat.z.ai default (small file). The real SIE
    # README is ~11KB — if it's <100 bytes, skip it. Otherwise deploy it.
    if [[ "$flat" == "README.md" ]]; then
      size=$(wc -c < "$f")
      if [[ "$size" -lt 100 ]]; then
        skipped_non_deliverable+=("$flat (chat.z.ai default, ${size}B)")
        echo "skip (non-deliverable): $flat (chat.z.ai default, ${size}B)" >> "$LOG"
        continue
      fi
      deploy_file "$flat"
      continue
    fi
    skipped_non_deliverable+=("$flat")
    echo "skip (non-deliverable): $flat" >> "$LOG"
    continue
  fi
  deploy_file "$flat"
done

# ── Summary ─────────────────────────────────────────────────────────────────
log_section "Deploy Summary"
{
  echo "Changed:              ${#changed[@]}"
  echo "Skipped (same):       ${#skipped_identical[@]}"
  echo "Skipped (owned):      ${#skipped_owned[@]}"
  echo "Skipped (non-delivr): ${#skipped_non_deliverable[@]}"
  echo "Manual deploys:       ${#manual_deploys[@]}"
} | tee -a "$LOG"

if [[ ${#changed[@]} -gt 0 ]]; then
  echo ""
  echo "Changed files:"
  echo "" >> "$LOG"
  echo "Changed files:" >> "$LOG"
  for f in "${changed[@]}"; do
    echo "  $f" | tee -a "$LOG"
  done
fi

if [[ ${#skipped_non_deliverable[@]} -gt 0 ]]; then
  echo ""
  echo "Skipped non-deliverable (left in scratch/):"
  echo "" >> "$LOG"
  echo "Skipped non-deliverable (left in scratch/):" >> "$LOG"
  for f in "${skipped_non_deliverable[@]}"; do
    echo "  $f" | tee -a "$LOG"
  done
fi

if [[ ${#manual_deploys[@]} -gt 0 ]]; then
  echo ""
  echo "Manual deploys (read-only destination):"
  echo "" >> "$LOG"
  echo "Manual deploys (read-only destination):" >> "$LOG"
  for f in "${manual_deploys[@]}"; do
    echo "  $f" | tee -a "$LOG"
  done
fi

# ── Install sie.py to ~/.local/bin/sie ──────────────────────────────────────
log_section "Installing sie.py -> $SIE_BIN"
mkdir -p "$(dirname "$SIE_BIN")"
cp -f "$DEST/sie.py" "$SIE_BIN"
chmod 755 "$SIE_BIN"

if command -v sie >/dev/null 2>&1; then
  sie --version
else
  echo "Warning: sie not on PATH yet." >&2
  echo "  Add ~/.local/bin to PATH in your shell rc." >&2
fi

# ── uv sync (idempotent — preserves existing .venv/) ──────────────────────────
log_section "uv sync"
cd "$DEST"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found in PATH. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

# `uv sync` is idempotent: if .venv/ exists and pyproject.toml hasn't
# changed, it's a no-op (no re-download). If deps changed or .venv/ is
# missing, it creates/updates the venv.
#
# `--no-install-project`: don't install the project itself (editable). The
# tests use `import sie` via conftest.py's sys.path.insert, not via the
# installed package.
#
# `--no-build` (SonarCloud shell:S8541): don't build source distributions —
# only use wheels. pytest + ruff both have wheels on PyPI.
uv sync --no-install-project --no-build --extra dev

# ── Lint gate (Shellcheck + Ruff) ────────────────────────────────────────────
# The gate runs Shellcheck on the deployed *.sh files + Ruff on the deployed
# *.py files (with autofix first). Non-fatal: the gate's output is logged
# but does NOT abort the deploy (the user reviews the output and decides
# whether to fix the issues). This mirrors LineByLine's approach.
#
# Note: run_lint_gate prints its own "=== Lint gate ===" header, so we
# don't call log_section here (that would produce a double header).
echo ""
echo "--- Lint gate ---"
if type run_lint_gate >/dev/null 2>&1; then
  if [[ ${#changed[@]} -gt 0 ]]; then
    changed_abs=()
    for rel in "${changed[@]}"; do
      changed_abs+=("$DEST/$rel")
    done
    run_and_log run_lint_gate "$DEST" "${changed_abs[@]}"
  else
    echo "  (no files changed this deploy — skipping lint gate)"
  fi
else
  echo "  (skipped: run_lint_gate not available — lint_gate.sh not sourced)"
fi

# ── SonarCloud exclusion coverage (non-blocking) ─────────────────────────────
# check_sonar_exclusions() (from lint_gate.sh) reads the deployed repo's
# .github/workflows/sonarcloud.yml and warns when a deployed path that carries
# coverage lines (Python / JS / TS) is in neither Dsonar.exclusions nor
# Dsonar.coverage.exclusions — either it needs tests or it needs an entry.
# Non-code paths are summarized without an action request (workflow YAML stays
# uncovered on purpose: its findings include unpinned action SHAs).
# Catching it here saves a follow-up commit. Non-fatal: output is logged only.
# Manual deploys count too — the user copies those into the repo by hand.
echo ""
echo "--- SonarCloud exclusion coverage (non-blocking) ---"
if type check_sonar_exclusions >/dev/null 2>&1; then
  if [[ ${#changed[@]} -gt 0 || ${#manual_deploys[@]} -gt 0 ]]; then
    run_and_log check_sonar_exclusions "$DEST" "${changed[@]}" "${manual_deploys[@]}"
  else
    echo "  (no files changed this deploy — skipping SonarCloud exclusion check)"
  fi
else
  echo "  (skipped: check_sonar_exclusions not available — lint_gate.sh not sourced)"
fi

# ── Tests ─────────────────────────────────────────────────────────────────────
# Non-fatal: test failures are logged but do NOT abort the deploy.
# Skip if no .py files changed this deploy (no code to test). Use -q for
# quiet output (dots for passing, full output for failures only).
echo ""
echo "--- Tests ---"
has_py_changes=0
for rel in "${changed[@]}"; do
  [[ "$rel" == *.py ]] && has_py_changes=1
done
if [[ "$has_py_changes" -eq 0 ]]; then
  echo "  (no .py files changed this deploy — skipping tests)"
else
  run_and_log .venv/bin/pytest tests/ -q --tb=short
fi

# ── Collision cleanup (scoped to zip-extracted files only) ─────────────────
# Remove ONLY the files that came from deliver.zip (per the manifest unpack.sh
# wrote to .deliver-files.list before extraction), plus deploy.sh itself.
# Pre-existing files in scratch/ (scratch.md notes, prior session's upload
# zips, anything the user stashed there) are NOT touched.
# Non-deliverable files (README.md, REFACTOR-NOTES.md, scratch.md) are also
# NOT cleaned up — they were left in scratch/ by the blocklist and should
# remain for the user.
log_section "Cleanup (scoped to zip-extracted files)"
DELIVER_LIST="$SCRATCH/.deliver-files.list"
if [[ ! -f "$DELIVER_LIST" ]]; then
  echo "WARNING: $DELIVER_LIST not found — unpack.sh may be out of date." >&2
  echo "         Skipping cleanup. Leftover zip-extracted files may collide with the next unzip." >&2
else
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ "$f" == "deploy.sh" || "$f" == "deliver.zip" || "$f" == ".deliver-files.list" ]] && continue
    # Skip non-deliverable files — they were left in scratch/ by the blocklist.
    if is_in_list "$f" "${non_deliverable[@]}"; then
      continue
    fi
    # Skip files that were deployed (mv'd by deploy_file) — they're no longer
    # in scratch/, so the [[ -f ]] guard skips them silently.
    full="$SCRATCH/$f"
    if [[ -f "$full" ]]; then
      echo "  rm: $f"
      rm -- "${full:?}"
    fi
  done < "$DELIVER_LIST"
fi

# ── Manual deploys ───────────────────────────────────────────────────────────
# Files that couldn't be deployed because the destination is read-only inside
# the bwrap sandbox. Print cp commands the user can run by hand. The file
# list was already printed in the Deploy Summary above — this section adds
# the cp commands for convenience.
if [[ ${#manual_deploys[@]} -gt 0 ]]; then
  echo ""
  echo "=== Manual deploys (copy these by hand) ===" | tee -a "$LOG"
  for f in "${manual_deploys[@]}"; do
    echo "  cp scratch/$f $DEST/$f" | tee -a "$LOG"
  done
fi

echo ""
echo "Done. scratch/ cleanup scoped to zip contents (pre-existing files preserved)." | tee -a "$LOG"
