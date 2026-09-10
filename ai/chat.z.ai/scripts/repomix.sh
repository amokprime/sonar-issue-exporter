#!/bin/bash
# repomix.sh — Repomix the sonar-issue-exporter repo and copy zip path to clipboard.
#
# Renamed from upload.sh in the v1.0.0 script-style refactor (both this and
# zip.sh are upload scripts; the new name distinguishes the Repomix path from
# the pure-zip path).
#
# Usage:
#   ./repomix.sh              # default: full repo repomix (covers whole repo —
#                            # one-time at session start is usually enough)
#   ./repomix.sh build        # build slice: sie.py + tests + ai/chat.z.ai/
#   ./repomix.sh skills       # skills slice: ai/chat.z.ai/skill + AGENTS + MEMORY
#
# Output: a unique-named .zip in $SCRATCH/ (path copied to clipboard for
# pasting into the chat.z.ai file picker).
#
# The repo is small enough that a naive full repomix works. For targeted
# sessions, pass "build" or "skills" as $1 to ship a slice.
#
# Setup:
#   - Repo root defaults to ~/GitHub/sonar-issue-exporter; override with
#     $SONAR_ISSUE_EXPORTER_ROOT env var.
#   - `repomix` looked up in ~/.npm-global/bin then PATH; install there or
#     adjust PATH in .base.sh.
#   - `wl-copy` for Wayland clipboard. On X11, replace with `xclip -sel c`.
#     On macOS, replace with `pbcopy`.

snippet() {
  if ! command -v repomix >/dev/null 2>&1; then
    echo "ERROR: repomix not found in PATH" >&2
    echo "Install: npm install -g repomix" >&2
    exit 1
  fi

  slice="${1:-full}"
  case "$slice" in
    full)
      # Full repo — everything except .gitignore'd paths (repomix respects .gitignore)
      repomix --output "$upload/repomix.xml"
      ;;
    build)
      # Build slice: source + tests + config (for agent build-test loop)
      local_include="sie.py"
      local_include+=",tests/**"
      local_include+=",pyproject.toml"
      local_include+=",ai/chat.z.ai/AGENTS.md"
      local_include+=",ai/chat.z.ai/MEMORY.md"
      local_include+=",ai/chat.z.ai/skill/**"
      repomix --output "$upload/repomix-build.xml" --include "$local_include"
      ;;
    skills)
      # Skills slice: agent context only (for meta-sessions on agent scaffolding)
      repomix --output "$upload/repomix-skills.xml" \
        --include "ai/chat.z.ai/skill/**,ai/chat.z.ai/AGENTS.md,ai/chat.z.ai/MEMORY.md"
      ;;
    *)
      echo "ERROR: unknown slice '$slice'. Use: full | build | skills" >&2
      exit 1
      ;;
  esac
}

# shellcheck source=.base.sh
. "$(dirname "$(readlink -f "$0")")/.base.sh"
