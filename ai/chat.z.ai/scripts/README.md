---
summary: Scripted uploads of the sonar-issue-exporter repo (Repomix or pure-zip) and batch "install" of agent-generated files. For use with web chat agents like chat.z.ai.
links:
  - "[[ai/chat.z.ai/AGENTS.md]]"
---

## Workflows

*Prepare local project files for upload.*

### repomix.sh
- Repomix the whole repo (default; `repomix` covers the whole sonar-issue-exporter repo, not just a slice, so this is largely one-time at session start)
- `build` slice: `sie.py` + `tests/**` + `pyproject.toml` + `ai/chat.z.ai/` (AGENTS, MEMORY, skills) for code-change sessions
- `skills` slice: `ai/chat.z.ai/skill/**` + `AGENTS.md` + `MEMORY.md` for meta-sessions on agent scaffolding
```
Follow `*-SKILL.md` files as rules.
```

### zip.sh
- Pure zip (no Repomix) of files staged in `scratch/upload/` — e.g. a `bug.zip` of debug logs + transcript, a `scriptstyle.zip` of reference scripts, a screenshot. Use when `repomix.sh` is the wrong tool.

## Delivery

*Batch "install" downloaded files the agent generated.*
### prepare.sh
- The agent fills out this template to funnel all "deliverables", including `deploy.sh`, into a `deliver.zip` file in its downloads folder.
### deploy.sh
- This copies changed files (not byte-identical to target) to the repo folder from the downloaded and unzipped files like a package installer. Also installs `sie.py` to `~/.local/bin/sie`, cleans up 0.2.x artifacts idempotently, runs `uv sync`, then runs `ruff check --fix` + `ruff check` (gate, includes C901 mccabe complexity) + `pytest`.
- The collision-cleanup at the end is scoped to only the files that came from `deliver.zip` (per a manifest `unpack.sh` writes before extraction). Pre-existing files in `scratch/` (notes, prior zips) are preserved.
### unpack.sh
- This is a wrapper to unzip `deliver.zip`, snapshot the zip contents for the scoped cleanup, run `deploy.sh`, and then remove `deliver.zip` + `deploy.sh` + the manifest.

## Setup
- Scripts default to the repo root `~/GitHub/sonar-issue-exporter`; set the `SONAR_ISSUE_EXPORTER_ROOT` environment variable to point somewhere else
- `repomix` is looked up in `~/.npm-global/bin` and then the rest of `PATH`; install it there or adjust `PATH` in `.base.sh`
- If not on a Fedora/Wayland distro, replace `wl-copy` with the equivalent (`xclip -sel c` on X11, `pbcopy` on macOS)
- Make the scripts executable (except for `.base.sh`, `prepare.sh`, and `deploy.sh`). Then configure `.base.sh` and `unpack.sh`.
    - They assume the repo is at `~/GitHub/sonar-issue-exporter`, and the zip is downloaded into `~/GitHub/sonar-issue-exporter/scratch/`
    - If your paths differ, customize paths and add an exception for `unpack.sh`'s path (i.e. `nano .git/info/exclude`)
    - The workflow scripts (`repomix.sh`, `zip.sh`) can be blindly double-clicked after setup, but `unpack.sh` should be run from the terminal to view output
- For Fish shell: add an abbreviation  or alias so `dsie` from any terminal runs the full unpack → deploy → lint → test → cleanup pipeline:
```fish
abbr --add dsie '~/GitHub/sonar-issue-exporter/ai/chat.z.ai/scripts/delivery/unpack.sh'
```

## Features
- Fails fast in strict mode (`set -euo pipefail`): if repomix or zip fails, the script aborts before deleting anything or copying a stale path to the clipboard
- Zips the upload folder's visible files, then clears the folder so the next run starts fresh
- `repomix.sh` runs the repomix command via a `snippet()` function defined before sourcing `.base.sh` (mirrors LineByLine's `.base.sh` pattern). `zip.sh` reuses the same base — it just defines a different `snippet()` (an empty-guard instead of a repomix invocation)
- `zip.sh` aborts with an error if the upload folder is empty (nothing to zip)
- Gives each zip file a unique name to prevent upload filenames colliding with stale server-side files. It's the current date in nanoseconds (`date +%s%N`), which should also help in tracing future upload bugs
- Copies the zip file's path to clipboard with `wl-copy` to paste into file picker path field when uploading
- `deploy.sh` cleanup is scoped to only the files that came from `deliver.zip` (per a manifest `unpack.sh` writes before extraction). Pre-existing files in `scratch/` — notes, prior session zips, anything the user stashed there — are preserved. A prior version used `find . -maxdepth 1 -type f` and swept every file in `scratch/`, deleting a user's `scratch.md` notes; see `archive/1.0.0/bug.md` for the post-mortem
