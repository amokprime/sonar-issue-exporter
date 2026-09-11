#!/bin/bash
# deploy.sh — deploys session files from cwd (where deliver.zip was extracted)
# to the sonar-issue-exporter repo, then cleans up 0.2.x artifacts and runs
# the Ruff gate + test suite.
#
# Called by unpack.sh after extraction. This file is committed at
# ai/chat.z.ai/scripts/delivery/deploy.sh as a template — each session, the
# agent fills in the file mappings below and includes the filled-in copy
# inside deliver.zip. The user's `dsie` fish abbreviation runs unpack.sh
# which extracts the zip and calls this script.
#
# This script SUPERSEDES sie-migrate.sh (which only handled the install).
# It does five things:
#   1. Deploy changed files from the zip to the repo (byte-identical skipped)
#   2. Install sie.py to ~/.local/bin/sie (the "migrate" step)
#   3. Clean up 0.2.x artifacts (build/, .venv/, requirements.txt, etc.)
#   4. Run `uv sync` (recreate .venv/ if missing or deps changed)
#   5. Run `ruff check --fix sie.py` (autofix) + `ruff check sie.py` (gate) + pytest
#
# Code quality per code-quality-SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - DEST derived from $HOME + SONAR_ISSUE_EXPORTER_ROOT override
#   - Arrays instead of word-splitting for file lists
#   - Errors on stderr with explicit exit codes

set -euo pipefail

DEST="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
SCRATCH="$DEST/scratch"
SIE_BIN="${XDG_BIN_HOME:-$HOME/.local/bin}/sie"

# Arrays for the summary — collect results as we go.
changed=()
skipped_identical=()
skipped_missing=()

# deploy_file <flat_filename> <repo_relative_path>
# Moves the file if it differs from the destination; skips if byte-identical.
# Always removes the source file (so the extraction directory stays clean).
deploy_file() {
  local src="$1"
  local rel="$2"
  local dst="$DEST/$rel"

  if [[ ! -f "$src" ]]; then
    skipped_missing+=("$src")
    echo "skip (missing): $src"
    return 0
  fi

  if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
    skipped_identical+=("$rel")
    echo "skip (identical): $rel"
    rm -- "${src:?}"
  else
    mkdir -p "$(dirname "$dst")"
    mv -- "$src" "$dst"
    changed+=("$rel")
    echo "deployed: $rel"
  fi
}

# ── File mappings ───────────────────────────────────────────────────────────
# Format: deploy_file <flat_filename> <repo_relative_path>
# Files not present in the zip are silently skipped ("skip (missing)") —
# expected when a turn ships a subset.

# Repo root files (recovered from a previous cleanup-bug accident + version bump)
deploy_file .gitignore                                   .gitignore
deploy_file .gitattributes                                .gitattributes
deploy_file LICENSE                                       LICENSE
deploy_file uv.lock                                       uv.lock

# Source + docs + config
deploy_file sie.py                                        sie.py
deploy_file sie-migrate.sh                                sie-migrate.sh
deploy_file README.md                                     README.md
deploy_file CONTRIBUTING.md                                CONTRIBUTING.md
deploy_file pyproject.toml                                pyproject.toml

# docs/ atomic notes (split out from README for skimmability)
deploy_file docs-input-forms.md                           docs/input-forms.md
deploy_file docs-output-paths.md                          docs/output-paths.md
deploy_file docs-local-migration.md                       docs/local-migration.md
deploy_file docs-clean-mode.md                            docs/clean-mode.md
deploy_file docs-auth-boundary.md                         docs/auth-boundary.md
deploy_file docs-troubleshooting-token.md                 docs/troubleshooting-token.md

# Tests
deploy_file tests-README.md                               tests/README.md
deploy_file tests-conftest.py                             tests/conftest.py
deploy_file tests-test_cli.py                             tests/test_cli.py
deploy_file tests-test_github_url.py                      tests/test_github_url.py
deploy_file tests-test_input_resolver.py                  tests/test_input_resolver.py
deploy_file tests-test_local_migration.py                tests/test_local_migration.py
deploy_file tests-test_markdown_render.py                 tests/test_markdown_render.py
deploy_file tests-test_output_paths.py                    tests/test_output_paths.py
deploy_file tests-test_url_parsing.py                     tests/test_url_parsing.py

# Agent context
deploy_file ai-chat.z.ai-AGENTS.md                    ai/chat.z.ai/AGENTS.md
deploy_file ai-chat.z.ai-MEMORY.md                    ai/chat.z.ai/MEMORY.md

# Skills
deploy_file ai-chat.z.ai-skill-code-quality-SKILL.md      ai/chat.z.ai/skill/code-quality-SKILL.md
deploy_file ai-chat.z.ai-skill-skill-SKILL.md             ai/chat.z.ai/skill/skill-SKILL.md
deploy_file ai-chat.z.ai-skill-sonarqube-workflow-SKILL.md ai/chat.z.ai/skill/sonarqube-workflow-SKILL.md
deploy_file ai-chat.z.ai-skill-web-channel-SKILL.md       ai/chat.z.ai/skill/web-channel-SKILL.md

# Scripts (this pipeline)
deploy_file ai-chat.z.ai-scripts-README.md            ai/chat.z.ai/scripts/README.md
deploy_file ai-chat.z.ai-scripts-.base.sh              ai/chat.z.ai/scripts/.base.sh
deploy_file ai-chat.z.ai-scripts-repomix.sh            ai/chat.z.ai/scripts/repomix.sh
deploy_file ai-chat.z.ai-scripts-zip.sh                ai/chat.z.ai/scripts/zip.sh
deploy_file ai-chat.z.ai-scripts-delivery-prepare.sh  ai/chat.z.ai/scripts/delivery/prepare.sh
deploy_file ai-chat.z.ai-scripts-delivery-deploy.sh   ai/chat.z.ai/scripts/delivery/deploy.sh
deploy_file ai-chat.z.ai-scripts-delivery-unpack.sh   ai/chat.z.ai/scripts/delivery/unpack.sh

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Deploy Summary ==="
echo "Changed:           ${#changed[@]}"
echo "Skipped (same):    ${#skipped_identical[@]}"
echo "Skipped (missing): ${#skipped_missing[@]}"

if [[ ${#changed[@]} -gt 0 ]]; then
  echo ""
  echo "Changed files:"
  for f in "${changed[@]}"; do
    echo "  $f"
  done
fi

# ── Install sie.py to ~/.local/bin/sie ──────────────────────────────────────
echo ""
echo "=== Installing sie.py -> $SIE_BIN ==="
mkdir -p "$(dirname "$SIE_BIN")"
cp -f "$DEST/sie.py" "$SIE_BIN"
chmod 755 "$SIE_BIN"

if command -v sie >/dev/null 2>&1; then
  sie --version
else
  echo "Warning: sie not on PATH yet." >&2
  echo "  Add ~/.local/bin to PATH in your shell rc." >&2
fi

# ── Clean up 0.2.x artifacts (idempotent) ────────────────────────────────────
echo ""
echo "=== Cleaning up 0.2.x artifacts (idempotent) ==="

rm_if_exists() {
  local target="$1"
  local label="$2"
  if [[ -e "$target" ]] || [[ -L "$target" ]]; then
    rm -rf -- "${target:?}"
    echo "  removed: $label"
  else
    echo "  already gone: $label"
  fi
}

# Old uv tool (if installed)
if command -v uv >/dev/null 2>&1; then
  if uv tool list 2>/dev/null | grep -q "^sonar-issue-exporter"; then
    echo "  removing old uv tool: sonar-issue-exporter"
    uv tool uninstall sonar-issue-exporter
  else
    echo "  already gone: uv tool sonar-issue-exporter"
  fi
else
  echo "  uv not on PATH — skipping uv tool check"
fi

# Old symlinks
rm_if_exists "$HOME/.local/bin/sonar-export" "sonar-export symlink"
rm_if_exists "$HOME/.local/bin/sonar-watch" "sonar-watch symlink"

# 0.2.x build/install artifacts in the repo
rm_if_exists "$DEST/build"                          "build/ (setuptools artifacts)"
rm_if_exists "$DEST/sonar_issue_exporter.egg-info"  "egg-info/ (setuptools metadata)"
rm_if_exists "$DEST/requirements.txt"               "requirements.txt (0.2.x dep file)"
rm_if_exists "$DEST/sample.env"                     "sample.env (0.2.x config template)"
rm_if_exists "$DEST/ruff.toml"                      "ruff.toml (superseded by pyproject.toml)"
rm_if_exists "$DEST/.ruff_cache"                    ".ruff_cache/ (old ruff cache)"
rm_if_exists "$DEST/uv.lock"                       "uv.lock (regenerated by uv sync)"
rm_if_exists "$DEST/.venv"                         ".venv/ (recreated by uv sync)"
rm_if_exists "$DEST/export_sonar_issue.py"          "export_sonar_issue.py (0.2.x source)"
rm_if_exists "$DEST/watch_clipboard.py"             "watch_clipboard.py (0.2.x source)"

# ── uv sync + ruff + pytest ───────────────────────────────────────────────────
echo ""
echo "=== uv sync (recreate .venv/ if needed) ==="
cd "$DEST"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found in PATH. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

# `uv sync` is idempotent: if .venv/ exists and pyproject.toml hasn't
# changed, it's a no-op. If deps changed (new test added, etc.) or
# .venv/ was deleted, it recreates the venv with the exact deps
# from pyproject.toml [project.optional-dependencies] dev = [...].
#
# `--no-install-project`: don't install the project itself (editable). The
# tests use `import sie` via conftest.py's sys.path.insert, not via the
# installed package — so the project doesn't need to be installed.
#
# `--no-build` (SonarCloud shell:S8541): don't build source distributions —
# only use wheels. pytest + ruff both have wheels on PyPI, so this is safe
# and prevents arbitrary build-script execution if a dep is compromised.
# (Requires `--no-install-project` because the project itself is an editable
# source distribution that would need building.)
uv sync --no-install-project --no-build --extra dev

echo ""
echo "=== Lint (ruff autofix + gate) ==="
# Run ruff/pytest directly from .venv/bin/ instead of `uv run` to avoid
# SonarCloud shell:S8541 (which flags `uv run` as a potential build-script
# execution vector). The venv is already synced above, so direct binary
# invocation is equivalent and faster (no uv overhead).
.venv/bin/ruff check --fix sie.py
.venv/bin/ruff check sie.py

echo ""
echo "=== Running tests ==="
.venv/bin/pytest tests/ -v

# ── Collision cleanup (scoped to zip-extracted files only) ─────────────────
# Remove ONLY the files that came from deliver.zip (per the manifest unpack.sh
# wrote to .deliver-files.list before extraction), plus deploy.sh itself.
# Pre-existing files in scratch/ (scratch.md notes, prior session's upload
# zips, anything the user stashed there) are NOT touched.
#
# Why not `find . -maxdepth 1 -type f`? A prior version of this script did
# that and swept every file in scratch/, deleting a user's scratch.md notes
# (the second time this bug class bit — see archive/1.0.0/bug.md for the
# first, which deleted repo-root files because the cd-after-uv-sync was
# missing). The scoped-list approach is safer: only files the agent put
# there get cleaned up.
#
# deploy.sh can't self-delete (unpack.sh handles it); deliver.zip is also
# left for unpack.sh. Files that the deploy_file mappings already moved
# or rm'd above won't exist anymore — the `[[ -f "$f" ]]` guard skips them
# silently.
echo ""
echo "=== Cleanup (scoped to zip-extracted files) ==="
DELIVER_LIST="$SCRATCH/.deliver-files.list"
if [[ ! -f "$DELIVER_LIST" ]]; then
  echo "WARNING: $DELIVER_LIST not found — unpack.sh may be out of date." >&2
  echo "         Skipping cleanup. Leftover zip-extracted files may collide with the next unzip." >&2
else
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    # $f is the basename as stored in the zip (flat, no subdirs). Skip the
    # two files unpack.sh owns — it removes them after deploy.sh exits.
    [[ "$f" == "deploy.sh" || "$f" == "deliver.zip" || "$f" == ".deliver-files.list" ]] && continue
    full="$SCRATCH/$f"
    if [[ -f "$full" ]]; then
      echo "  rm: $f"
      rm -- "${full:?}"
    fi
  done < "$DELIVER_LIST"
fi

echo ""
echo "Done. scratch/ cleanup scoped to zip contents (pre-existing files preserved)."