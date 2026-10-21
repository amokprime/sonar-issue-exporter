#!/bin/bash
# unpack.sh — user-side deployment script for sonar-issue-exporter.
# Double-click in a file manager OR run from a terminal — the script
# re-launches itself in a popup ghostty window when stdout is not a TTY
# (double-click case), so deploy output is visible either way.
#
# Thin wrapper: extracts deliver.zip to scratch/, snapshots the zip
# contents so deploy.sh can do scoped cleanup, runs deploy.sh inside a
# bwrap sandbox for extra safety, then removes deploy.sh + deliver.zip
# + .deliver-files.list.
#
# The heavy lifting (deploy files, install sie.py, run lint gate + tests,
# scoped cleanup) lives in skills/delivery/scripts/deploy.sh — keeps
# unpack.sh a thin wrapper that just handles extraction + sandbox setup
# + handoff.
#
# bwrap sandbox (if available):
#   --clearenv: clears all env vars, then re-adds only what deploy.sh needs
#   Read-only overlays: .git/, archive/, unpack.sh itself (the bwrap filter)
#   Read-write: repo root ($DEST) — deploy.sh deploys files here
#   Read-write: ~/.local — deploy.sh installs sie.py to ~/.local/bin/sie
#   If bwrap isn't installed, deploy.sh runs directly with a warning.
#
# Tradeoff: unpack.sh is read-only inside the sandbox. Future edits to
# unpack.sh must be deployed manually (copy the file, don't use the
# deliver.zip pipeline) — a malicious deliver.zip can't modify the
# bwrap filter for future runs.
#
# Code quality per skills/code-quality/SKILL.md → "Bash workflow scripts":
#   - set -euo pipefail
#   - ${var:?} guards on every rm with a variable path (SC2115)
#   - SONAR_ISSUE_EXPORTER_ROOT override (config over constants)
#   - unzip -oqq — -o overwrites stale files from a failed previous run
#   - EXIT trap cleans up deploy.sh + deliver.zip + .deliver-files.list on
#     ALL exits (success, failure, signal)

set -euo pipefail

# ── Popup terminal on double-click ──────────────────────────────────────────
# When double-clicked in a file manager, stdout is NOT a TTY. Re-launch
# ourselves in a popup ghostty window so deploy output is visible.
# Terminal invocations already have a TTY and skip this branch.
# The `exec` replaces the current process so we don't leave a stray shell.
# SIE_POPUP=1 is passed through so the re-launched script knows to pause at
# the end (otherwise ghostty closes immediately after the script finishes).
if [[ ! -t 1 ]]; then
  if command -v ghostty >/dev/null 2>&1; then
    # ghostty -e runs the rest of its args as a command. We re-exec this
    # script with all original args preserved. The `bash -c` form lets us
    # rebuild the arg list cleanly without SC2145 (mixing string + array).
    exec ghostty -e bash -c 'SIE_POPUP=1 exec "$@"' _ "$0" "$@"
  fi
  # If ghostty isn't installed, fall through to running without a TTY —
  # output goes to wherever the file manager routed it (usually nowhere
  # visible). The user sees the deploy only via the notify-send at the end.
  echo "WARNING: stdout is not a TTY and ghostty is not installed." >&2
  echo "WARNING: install ghostty, or run scripts/unpack.sh from a terminal." >&2
fi

DEST="${SONAR_ISSUE_EXPORTER_ROOT:-$HOME/GitHub/sonar-issue-exporter}"
SCRATCH="$DEST/scratch"
DELIVER_ZIP="$SCRATCH/deliver.zip"
DEPLOY_SH="$SCRATCH/deploy.sh"
DELIVER_LIST="$SCRATCH/.deliver-files.list"

# ── EXIT-trap cleanup ────────────────────────────────────────────────────────
# Runs on ALL exits -- success, set -e failure, INT/TERM signal.
cleanup() {
  rm -f -- "${DEPLOY_SH:?}" "${DELIVER_ZIP:?}" "${DELIVER_LIST:?}"
  echo "" >&2
  echo "Cleaned up deploy.sh + deliver.zip + .deliver-files.list." >&2
}
trap cleanup EXIT

# ── Sanity checks ────────────────────────────────────────────────────────────
if [[ ! -d "$SCRATCH" ]]; then
  echo "ERROR: scratch dir not found: $SCRATCH" >&2
  exit 1
fi
if [[ ! -f "$DELIVER_ZIP" ]]; then
  echo "ERROR: deliver.zip not found at $DELIVER_ZIP" >&2
  echo "Download deliver.zip from the chat first." >&2
  exit 1
fi

cd "$SCRATCH"

# Snapshot the zip's contents before extraction so deploy.sh can clean up
# ONLY the files that came from the zip (plus deliver.zip and deploy.sh).
unzip -l "$DELIVER_ZIP" | awk 'NR>3 && $4 != "" {print $4}' > "$DELIVER_LIST"

# Extract (-o overwrites stale files from a failed previous run; -qq = quiet).
unzip -oqq "$DELIVER_ZIP"

# Run deploy.sh
chmod +x "$DEPLOY_SH"

# ── bwrap sandbox ────────────────────────────────────────────────────────────
# If bwrap is available, run deploy.sh inside a sandbox with:
#   - Cleared env (only essential vars passed through — no SSH, no Syncthing,
#     no API keys needed for SIE's deploy)
#   - Read-only system paths (/usr, /etc, /lib, /bin, /sbin, /run)
#   - Read-write: /tmp, /dev, /proc, repo root ($DEST)
#   - Read-write: ~/.local (deploy.sh installs sie.py to ~/.local/bin/sie;
#     ruff/pytest may also live there as symlinks into ~/.local/share)
#   - Read-only overlays on .git/, archive/, unpack.sh (the filter itself)
#
# Warnings when a deploy runs into the filter:
#   - Read-only paths: EROFS errors from deploy.sh commands naturally appear
#     in the output.
#
# If bwrap is NOT available, run deploy.sh directly with a warning.
if command -v bwrap >/dev/null 2>&1; then
  bwrap_args=()

  # ── opt_ro / opt_bind helpers ──────────────────────────────────────────
  # Append a --ro-bind or --bind if the path exists, else log a warning so
  # the missing bind is visible (not silently skipped). The deploy can
  # still proceed — the path is just not protected this run.
  opt_ro() {
    if [[ -e "$1" ]]; then
      bwrap_args+=(--ro-bind "$1" "$1")
    else
      echo "unpack.sh: WARN: read-only bind skipped (path missing): $1" >&2
    fi
  }
  opt_bind() {
    if [[ -e "$1" ]]; then
      bwrap_args+=(--bind "$1" "$1")
    else
      echo "unpack.sh: WARN: bind skipped (path missing): $1" >&2
    fi
  }

  # ── Clear env, re-add essentials ─────────────────────────────────────────
  # SIE's deploy.sh needs: HOME (for ~/.local/bin/sie), USER, PATH (for uv,
  # ruff, pytest, shellcheck), SONAR_ISSUE_EXPORTER_ROOT (the repo root).
  # No SSH, no Syncthing, no API keys — SIE's deploy is a pure local install.
  bwrap_args+=(
    --clearenv
    --setenv HOME "$HOME"
    --setenv USER "${USER:-$(whoami)}"
    --setenv PATH "$PATH"
    --setenv SONAR_ISSUE_EXPORTER_ROOT "$DEST"
  )

  # Display/DBus for notify-send at the end of deploy.sh (optional)
  [[ -n "${DISPLAY:-}" ]] && bwrap_args+=(--setenv DISPLAY "$DISPLAY")
  [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && bwrap_args+=(--setenv DBUS_SESSION_BUS_ADDRESS "$DBUS_SESSION_BUS_ADDRESS")
  [[ -n "${XDG_RUNTIME_DIR:-}" ]] && bwrap_args+=(--setenv XDG_RUNTIME_DIR "$XDG_RUNTIME_DIR")

  # ── System paths (read-only) ────────────────────────────────────────────
  # /usr contains binaries (uv, python3, shellcheck, curl, jq) + libraries.
  # /etc contains resolv.conf (DNS), ssh_config (not used by SIE but harmless).
  # These are mandatory — without them the sandbox can't function.
  bwrap_args+=(
    --ro-bind /usr /usr
    --ro-bind /etc /etc
    --bind /tmp /tmp
    --dev /dev
    --proc /proc
  )

  # Distro-specific symlink paths (Fedora: /lib → /usr/lib, /bin → /usr/bin, etc.)
  # Optional — not all distros have all of these as separate paths.
  for p in /lib /lib64 /bin /sbin; do
    opt_ro "$p"
  done

  # /run for D-Bus socket (read-only -- connectable but can't create/delete
  # files in /run).
  opt_ro /run

  # ── ~/.local (read-write) ────────────────────────────────────────────────
  # deploy.sh installs sie.py to ~/.local/bin/sie, so ~/.local must be
  # read-write. Bind all of ~/.local, NOT just ~/.local/bin: the executables
  # there are commonly symlinks whose targets live under ~/.local/share (e.g.
  # `ruff -> ~/.local/share/uv/tools/ruff/bin/ruff`). Binding only
  # ~/.local/bin leaves the symlink dangling in the sandbox.
  opt_bind "$HOME/.local"

  # ── Repo root (read-write -- deploy.sh deploys files here) ───────────────
  bwrap_args+=(--bind "$DEST" "$DEST")

  # ── Read-only overlays (must come AFTER --bind above to take effect) ────
  # .git/ -- git history shouldn't be modified by deploy
  opt_ro "$DEST/.git"
  # archive/ -- historical artifacts, read-only
  opt_ro "$DEST/archive"
  # unpack.sh itself -- the bwrap filter; must be deployed manually.
  opt_ro "$DEST/scripts/unpack.sh"

  # ── Run deploy.sh inside the sandbox ─────────────────────────────────────
  # Capture the exit code without aborting (set -e would close the popup
  # before the user can read the output). The pause below runs regardless.
  deploy_exit=0
  bwrap "${bwrap_args[@]}" -- "$DEPLOY_SH" || deploy_exit=$?
else
  echo "WARNING: bwrap not installed -- running deploy.sh without sandbox." >&2
  echo "WARNING: install bubblewrap (dnf install bubblewrap) for sandbox isolation." >&2
  deploy_exit=0
  "$DEPLOY_SH" || deploy_exit=$?
fi

if [[ "$deploy_exit" -ne 0 ]]; then
  echo ""
  echo "ERROR: deploy.sh exited with code $deploy_exit" >&2
  echo "  Check scratch/upload/deploy.log for details."
fi

echo "Done."

# ── Pause if running in popup mode ──────────────────────────────────────────
# Always runs (success or failure) so the user can read the output before
# the popup window closes. Terminal invocations don't set SIE_POPUP, so
# they exit immediately.
if [[ "${SIE_POPUP:-0}" == "1" ]]; then
  echo ""
  read -rp "Press Enter to close this window..."
fi

exit "$deploy_exit"
