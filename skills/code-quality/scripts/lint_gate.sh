#!/bin/bash
# lint_gate.sh -- shared blocking lint gate for Bash + Python.
#
# Lives at skills/code-quality/scripts/lint_gate.sh — owned by the
# code-quality skill. Sourced by both prepare.sh (sandbox-side, before
# zipping) and deploy.sh (user-side, after deploying files). Runs every
# linter that's installed; fails (exit 1) if any linter finds issues
# after autofix.
#
# Usage (source this file, then call run_lint_gate):
#   . /path/to/lint_gate.sh
#   run_lint_gate "$TARGET_DIR" [<changed_files...>]
#
# Linters run (in order):
#   1. Shellcheck -- *.sh files (no autofix; blocking on findings)
#   2. Ruff -- *.py files (autofix via `ruff check --fix`, then gate via `ruff check`)
#
# Each linter is skipped if not installed or if no matching files exist.
# The gate is BLOCKING: if any linter that IS installed finds issues after
# autofix, the function returns 1 (and the caller should exit).
#
# Also defines check_sonar_exclusions() -- a non-blocking JIT reminder that
# warns when a deployed repo-relative path that SonarCloud analyzes is not
# covered by .github/workflows/sonarcloud.yml's exclusion lists.

set -euo pipefail

# run_lint_gate <target_dir> [<changed_files...>]
#   target_dir: the directory to lint (repo root or scratch/)
#   changed_files: optional, absolute paths of specific files changed this
#     deploy. If provided, Shellcheck/Ruff scan ONLY these files (not the
#     full target_dir depth-0 scan). If not provided, falls back to the
#     find-based depth-0 scan (prepare.sh context).
run_lint_gate() {
  local target_dir="$1"
  shift
  local changed_files=("$@")
  local lint_failed=0

  echo "=== Lint gate (Shellcheck + Ruff) ==="
  echo "  Target: $target_dir"
  if [[ ${#changed_files[@]} -gt 0 ]]; then
    echo "  Mode: changed-files-only (${#changed_files[@]} file(s))"
  else
    echo "  Mode: depth-0 scan"
  fi

  # ── Shellcheck ──────────────────────────────────────────────────────────────
  echo ""
  echo "--- Shellcheck (*.sh) ---"
  local sh_bin=""
  if command -v shellcheck >/dev/null 2>&1; then
    sh_bin="shellcheck"
  elif [[ -f "$target_dir/.venv/bin/shellcheck" ]]; then
    sh_bin="$target_dir/.venv/bin/shellcheck"
  fi
  if [[ -z "$sh_bin" ]]; then
    echo "  (skipped: shellcheck not installed)"
    echo "  Install via: dnf install shellcheck (Fedora) or apt install shellcheck (Debian)"
  else
    local sh_files=()
    if [[ ${#changed_files[@]} -gt 0 ]]; then
      # Changed-files mode: only lint .sh files from the changed list
      for f in "${changed_files[@]}"; do
        [[ -f "$f" && "$f" == *.sh ]] && sh_files+=("$f")
      done
    else
      # Depth-0 scan mode: find all .sh files in the target dir
      while IFS= read -r f; do
        sh_files+=("$f")
      done < <(find "$target_dir" -maxdepth 1 -name '*.sh' -type f | sort)
      # Also check dotfile scripts (e.g. .foo.sh — if any exist)
      while IFS= read -r f; do
        sh_files+=("$f")
      done < <(find "$target_dir" -maxdepth 1 -name '.*.sh' -type f | sort)
    fi

    if [[ ${#sh_files[@]} -eq 0 ]]; then
      if [[ ${#changed_files[@]} -gt 0 ]]; then
        echo "  (no .sh files changed this deploy)"
      else
        echo "  (no .sh files found in $target_dir)"
      fi
    else
      local sh_failed=0
      for f in "${sh_files[@]}"; do
        if ! "$sh_bin" -x "$f" 2>&1; then
          echo "  FAIL: $f" >&2
          sh_failed=1
        fi
      done
      if [[ "$sh_failed" -ne 0 ]]; then
        echo "  Shellcheck gate FAILED -- fix the issues above." >&2
        lint_failed=1
      else
        echo "  Shellcheck clean (${#sh_files[@]} files)."
      fi
    fi
  fi

  # ── Ruff (Python) ───────────────────────────────────────────────────────────
  echo ""
  echo "--- Ruff (*.py) ---"
  # Resolve ruff binary: prefer PATH, then ~/.local/bin/ruff, then .venv/bin/ruff
  # (SIE uses `uv sync` which installs ruff to .venv/bin/).
  local ruff_bin=""
  if command -v ruff >/dev/null 2>&1; then
    ruff_bin="ruff"
  elif [[ -x "$HOME/.local/bin/ruff" ]]; then
    ruff_bin="$HOME/.local/bin/ruff"
  elif [[ -f "$target_dir/.venv/bin/ruff" ]]; then
    ruff_bin="$target_dir/.venv/bin/ruff"
  fi
  if [[ -z "$ruff_bin" ]]; then
    echo "  (skipped: ruff not installed)"
    echo "  Install via: uv sync --no-install-project --no-build --extra dev (creates .venv/ with ruff)"
  else
    local py_files=()
    if [[ ${#changed_files[@]} -gt 0 ]]; then
      # Changed-files mode: only lint .py files from the changed list
      for f in "${changed_files[@]}"; do
        [[ -f "$f" && "$f" == *.py ]] && py_files+=("$f")
      done
    else
      # Depth-0 scan mode: find all .py files in the target dir
      while IFS= read -r f; do
        py_files+=("$f")
      done < <(find "$target_dir" -maxdepth 1 -name '*.py' -type f | sort)
    fi

    if [[ ${#py_files[@]} -eq 0 ]]; then
      if [[ ${#changed_files[@]} -gt 0 ]]; then
        echo "  (no .py files changed this deploy)"
      else
        echo "  (no .py files found in $target_dir)"
      fi
    else
      # Autofix first
      echo "  Running ruff check --fix..."
      "$ruff_bin" check --fix "${py_files[@]}" 2>&1 || true
      # Gate (blocking)
      if ! "$ruff_bin" check "${py_files[@]}" 2>&1; then
        echo "  Ruff gate FAILED -- fix the issues above." >&2
        lint_failed=1
      else
        echo "  Ruff clean (${#py_files[@]} files)."
      fi
    fi
  fi

  # ── Summary ─────────────────────────────────────────────────────────────────
  echo ""
  if [[ "$lint_failed" -ne 0 ]]; then
    echo "  === Lint gate: FAILED ===" >&2
    echo "  Fix the issues above, then re-run." >&2
    return 1
  else
    echo "  === Lint gate: PASSED ==="
  fi
}

# check_sonar_exclusions <repo_root> [<rel_path>...]
#   Non-blocking JIT reminder: warns when a deployed repo-relative path is NOT
#   covered by either Dsonar.exclusions or Dsonar.coverage.exclusions in
#   <repo_root>/.github/workflows/sonarcloud.yml.
#
#   Paths are passed in by the caller (deploy.sh passes the rel-paths it just
#   deployed). SIE's deploy.sh derives rel-paths at runtime by decoding `__`-flat
#   zip names, so there is no static deploy_file mapping table to parse --
#   unlike LineByLine's version of this function.
#
#   Only coverage-counted code paths (Python / JS / TS families) are reported
#   as warnings -- those are the only paths an exclusion entry, or a missing
#   test, can affect. Everything else is summarized in one line: non-code types
#   (YAML, shell, Markdown, TOML, lockfiles) carry no coverage lines, so
#   excluding them hides findings without buying anything. Workflow YAML is
#   deliberately left uncovered in this repo, so that SonarCloud keeps
#   reporting findings on it (for example unpinned action SHAs).
#   Verify with:
#     curl -s "https://sonarcloud.io/api/measures/component_tree?component=amokprime_sonar-issue-exporter&metricKeys=ncloc,lines_to_cover,coverage&qualifiers=FIL&ps=50"
#   (lines_to_cover is set for *.py, absent for *.sh / *.yml in this repo)
#
#   Non-blocking: returns 0 even if uncovered paths are found (warning only).
#   Skips silently if no paths are passed or if sonarcloud.yml is missing.
check_sonar_exclusions() {
  local repo_root="${1:-}"
  [[ $# -gt 0 ]] && shift
  local sonar_yml="$repo_root/.github/workflows/sonarcloud.yml"

  if [[ $# -eq 0 ]]; then
    return 0
  fi

  if [[ ! -f "$sonar_yml" ]]; then
    echo "  (skipped: $sonar_yml not found)"
    return 0
  fi

  local exclusions=""
  local coverage_exclusions=""
  while IFS= read -r line; do
    case "$line" in
      *"-Dsonar.exclusions="*)
        exclusions="${line#*-Dsonar.exclusions=}"
        ;;
      *"-Dsonar.coverage.exclusions="*)
        coverage_exclusions="${line#*-Dsonar.coverage.exclusions=}"
        ;;
    esac
  done < "$sonar_yml"

  if [[ -z "$exclusions" && -z "$coverage_exclusions" ]]; then
    echo "  (skipped: no Dsonar.exclusions found in $sonar_yml)"
    return 0
  fi

  local patterns=()
  IFS=',' read -r -a patterns <<< "${exclusions},${coverage_exclusions}"

  local uncovered=()
  local no_action=()
  local rel pat matched
  for rel in "$@"; do
    [[ -z "$rel" ]] && continue
    matched=0
    for pat in "${patterns[@]}"; do
      [[ -z "$pat" ]] && continue
      if [[ "$rel" == "$pat" ]]; then
        matched=1
        break
      fi
      if [[ "${pat: -3}" == "/**" && "$rel" == "${pat:0:-3}"/* ]]; then
        matched=1
        break
      fi
    done
    [[ "$matched" -eq 1 ]] && continue
    case "$rel" in
      *.py|*.pyi|*.js|*.mjs|*.cjs|*.jsx|*.ts|*.tsx|*.vue)
        uncovered+=("$rel")
        ;;
      *)
        no_action+=("$rel")
        ;;
    esac
  done

  if [[ ${#uncovered[@]} -gt 0 ]]; then
    echo "  SonarCloud exclusion coverage warning:"
    echo "    Coverage-counted paths with no exclusion entry:"
    for f in "${uncovered[@]}"; do
      echo "      $f"
    done
    echo ""
    echo "    Either cover them with tests, or add them to Dsonar.exclusions"
    echo "    (skip analysis) / Dsonar.coverage.exclusions (analyze, skip"
    echo "    coverage) in .github/workflows/sonarcloud.yml -- saves a"
    echo "    separate commit."
    echo ""
    echo "    (Non-blocking warning -- the gate still proceeds.)"
  elif [[ ${#no_action[@]} -eq 0 ]]; then
    echo "  All deployed paths are covered by sonarcloud.yml exclusions."
  fi

  if [[ ${#no_action[@]} -gt 0 ]]; then
    echo "  Uncovered, no exclusion needed (${#no_action[@]} path(s)):"
    for f in "${no_action[@]}"; do
      echo "      $f"
    done
    echo "    YAML (workflows), shell, Markdown and other non-code types carry"
    echo "    no coverage lines, so an exclusion entry would only hide findings"
    echo "    -- workflow YAML stays uncovered on purpose, e.g. to keep"
    echo "    unpinned-action-SHA findings visible."
  fi

  return 0
}
