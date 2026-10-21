---
summary: Utility scripts for the sonar-issue-exporter repo — ad-hoc zip, user-side deploy wrapper, and diff-main capture for AI agent reproduction.
links:
  - "[[AGENTS.md]]"
  - "[[skills/sonar-issue-exporter/SKILL.md]]"
  - "[[skills/delivery/SKILL.md]]"
---
### Preparing uploads
```
scripts/zip.sh
```
- Zips whatever is in `$SONAR_ISSUE_EXPORTER_ROOT/scratch/upload/` into a uniquely-named zip in `scratch/`, then copies the path to clipboard via `wl-copy` (with `xclip`/`pbcopy` fallbacks). Aborts with an error if the upload folder is empty.
- Used for ad-hoc uploads of non-deliverable files (e.g. a single screenshot or test fixture). Can be double-clicked after setup.
- Self-contained (no `.base.sh` sourcing — the shared setup logic is folded in directly).
### Sharing uncommitted state
```
scripts/diff-main.sh
```
- Captures your local working tree state (uncommitted + untracked + unpushed commits) as a portable patch + metadata. The chat.z.ai agent can reproduce your local state by cloning the `main` branch and applying the patch. Use this when you made a lot of changes manually or with the OMP agent. This prevents the chat.z.ai agent from clobbering them on the next deploy.
- Output goes to `$REPO/scratch/upload/`:
    - `changes.patch` — `git diff --binary $BASE_SHA` covering tracked + untracked files (uses `git add -N .` to mark untracked files as intent-to-add, then `git reset` to undo)
    - `changes.status` — `git status --porcelain` (the authoritative pre-mutation state)
    - `changes.meta` — `base_ref`, `base_sha`, `head_sha`, `branch`, `status_file` pointer
- This project pushes directly to `main` (no staging branch), so the diff is against `origin/main`.
### "Installing" chat.z.ai sandbox changes locally
```
scripts/unpack.sh
```
- User-side wrapper that extracts `deliver.zip` to `scratch/`, snapshots the zip contents to `.deliver-files.list`, runs `skills/delivery/scripts/deploy.sh` inside a bwrap sandbox (if available), then cleans up.
- Double-click in a file manager OR run from a terminal. The script re-launches itself in a popup Ghostty window when it detects a non-TTY stdout. `SIE_POPUP=1` is passed through so the popup stays open after the script finishes.
- bwrap sandbox: `--clearenv` (re-adds only HOME, USER, PATH, SONAR_ISSUE_EXPORTER_ROOT, DISPLAY/DBus/XDG). Read-only system paths (/usr, /etc, /lib, /bin, /sbin, /run). Read-write repo root + `~/.local` (for `sie.py` install). Read-only overlays on `.git/`, `archive/`, and `unpack.sh` itself. If bwrap isn't installed, runs `deploy.sh` directly with a warning.
### Espanso snippets (for OMP sessions)
```
scripts/espanso.yml
```
- Espanso match file with triggers for the standard vibecoding-step context-loading instructions (`:onb`, `:code`, `:skl`). See `ai/README.md` for the current trigger list and descriptions.
- Install (hardlink so both copies stay in sync):
```sh
ln ~/.config/espanso/match/sonar-issue-exporter.yml scripts/espanso.yml
```
### Setup
- Scripts default to the repo root `~/GitHub/sonar-issue-exporter`. Set the `SONAR_ISSUE_EXPORTER_ROOT` environment variable to point somewhere else.
- If not on a Fedora/Wayland distro, replace `wl-copy` with the equivalent (`xclip -sel c` on X11, `pbcopy` on macOS).
- Set the executable bit on the scripts (except for `prepare.sh` and `deploy.sh` — those are not directly invoked).
    - They assume the repo is at `~/GitHub/sonar-issue-exporter`, and the zip is downloaded into `~/GitHub/sonar-issue-exporter/scratch/`.
    - If your paths differ, customize paths and add an exception for `unpack.sh`'s path (i.e. `nano .git/info/exclude`).
    - `zip.sh` can be blindly double-clicked after setup. `unpack.sh` can be double-clicked (popup Ghostty window) or run from a terminal.
### Features
- Fails fast in strict mode (`set -euo pipefail`): if zip fails, the script aborts before deleting anything or copying a stale path to the clipboard.
- Zips the upload folder's visible files, then clears the folder so the next run starts fresh.
- `zip.sh` aborts with an error if the upload folder is empty (nothing to zip).
- Gives each zip file a unique name to prevent upload filenames colliding with stale server-side files. It's the current date in nanoseconds (`date +%s%N`), which should also help in tracing future upload bugs.
- Sweeps stale zips from `scratch/` older than 1 hour (keeps recent ones from rapid successive runs).
- Copies the zip file's path to clipboard with `wl-copy` (or `xclip`/`pbcopy` fallback) to paste into file picker path field when uploading.
- `unpack.sh` re-launches itself in a popup Ghostty window when double-clicked (non-TTY stdout), so deploy output is visible either way. The popup stays open after the script finishes (`read -rp "Press Enter..."` gated on `SIE_POPUP=1`).
- `unpack.sh` runs `deploy.sh` inside a bwrap sandbox with `--clearenv`, read-only system paths, read-write repo root + `~/.local`, and read-only overlays on `.git/`, `archive/`, and `unpack.sh` itself.
- `deploy.sh` cleanup is scoped to only the files that came from `deliver.zip` (per a manifest `unpack.sh` writes before extraction). Pre-existing files in scratch/ are preserved.