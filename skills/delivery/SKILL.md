---
name: delivery
description: Package and deploy session deliverables from the chat.z.ai sandbox to the user's local sonar-issue-exporter repo, and the behavioral rules for the chat.z.ai web channel that apply every turn. Use this skill whenever you need to ship files (run `prepare.sh` to zip the download folder, include `deploy.sh` for the directory-walking deploy), when the user mentions `deliver.zip`, `unpack.sh`, chat.z.ai, download folder, web chat, Agent mode, uploads, or when the agent is unsure about file visibility, output format, or comment density. Also use when the agent is unsure when to re-read context after compaction, or when reviewing how sandbox vs. user-side environments differ.
---
This skill covers two related concerns: (1) the chat.z.ai web-channel behavioral rules that apply every turn, and (2) the delivery workflow (prepare → zip → deploy) and the scripts that automate it. The web channel is the only interaction surface — the agent cannot see the user's filesystem directly; deliverables must be copied to `download/` for the user to retrieve. The agent's context window compacts over long sessions, making early-turn instructions less reliable later — re-read this skill mid-session when that happens.

Onboarding + workflow steps live in the `sonar-issue-exporter` skill; the per-turn behavioral rules and the delivery scripts live here.

---
Web channel behavioral rules

These apply every turn, not just at onboarding. The agent is most likely to forget them in later turns as context compacts.

File visibility — the user can only see files inside `/home/z/my-project/download/`. Everything else (project tree, scripts, temp files) is invisible to them.

- Copy every deliverable to `download/` — the user cannot access other folders.
- Avoid subdirectories inside `download/` — the user cannot see them. Put files directly in `download/` or zip them.
- Don't clutter `download/` with compiled temporary files like `*.pyc` or `__pycache__/`. After running Python scripts, clean up.
- For multi-file sessions, use the prepare → deploy pattern (see "Workflow" below) — `prepare.sh` handles the zip + cleanup automatically.
- Keep `download/` clean between turns. `prepare.sh` removes loose files after zipping so only `deliver.zip` remains. At the start of the next turn, remove any stale `deliver.zip` before placing new files.
- Avoid spaces in filenames in `download/` — the download system URL-encodes spaces as `+`, causing "Failed to download file" errors. Use hyphens or underscores.

Input handling

- Stop immediately to request any missing uploads. Don't infer their contents — if the user refers to a file you haven't seen, ask for it.
- Read docs and manifests (i.e. `*.md`, `pyproject.toml`, `uv.lock`) before code (i.e. `*.py`, `*.sh`). Documentation describes intent; code is the implementation. Reading docs first prevents misinterpretation.

Output format

- Don't generate Office documents or PDFs. Just output to chat in English.
- Implement the strongly dominant solution as a drop-in code file for the user to run and test. Only stop and ask if the user's intention or environment are unclear, or if multiple competing solutions exist.

Comment density

Large comment blocks in code files are hard to maintain (comments rot faster than code). The rule differs by file type:

- `sie.py` and `tests/*.py`: minimal comments. Reserve 1-2 line comments for non-obvious decisions like workarounds, deferred bugs, intentional smells. Don't pedantically document every function — the top-of-file docstring + `--help` epilog + `README.md` cover usage.
- Standalone scripts (e.g. `scripts/unpack.sh`, `skills/delivery/scripts/deploy.sh`): larger header comment blocks are acceptable when they serve a functional purpose — usage examples, env var list, exit codes, or the chain of trust a reader needs before opening the file. But don't write a monolithic wall of text. The patterns to follow:
    - Lead with a one-line description of what the script does, then a blank line before the longer block.
    - Group related information into labeled sections (`# Usage:`, `# Env:`, `# Exit codes:`) so a reader can scan to what they need.
    - For CLI tools with flags, document each flag inline at the argparse/getopts level.
    - If the script sources or is sourced by another file, note the dependency in both files (the `# shellcheck source=` directive in Bash).
    - Keep the header under ~30 lines. If the script needs more documentation than that, it belongs in `scripts/README.md`.

For documentation that doesn't fit in a comment, pair a folder with a `README.md`. Don't use readmes as memory dumping grounds — preserve their structure for naive users and developers.

Context compaction

The agent has a large native context (~1M tokens) but may compact or re-read uploaded files in later turns. If you find yourself re-reading uploaded files, also re-read this skill — the channel rules are just as likely to have been forgotten as the file contents.

For sonar-issue-exporter specifically: when context compacts and you lose track of the current architecture (single-file script, `--migrate` flag, v1.1.0 CodeQL auto-discovery, etc.), re-read `MEMORY.md` first — it's the leanest summary and explicitly flags what training data shadows (e.g. "training data may suggest `uv tool install` — for `sie` 1.0.0+, the install is a single `install -Dm755 sie.py ~/.local/bin/sie`").

---
Sandbox vs. user-side environment

The chat.z.ai sandbox and the user's local machine are different environments. Commands that work locally may not work in-sandbox, and vice versa. This table disambiguates:

| Concern | Sandbox (chat.z.ai) | User-side (local machine) |
|---|---|---|
| Filesystem | `/home/z/my-project/` only; user sees `/home/z/my-project/download/` | `~/GitHub/sonar-issue-exporter` (SONAR_ISSUE_EXPORTER_ROOT override) |
| Pytest | `uv run pytest tests/ -v` (full suite, ~182 specs, <1s, no network) | same — the suite is sandbox-runnable end-to-end |
| SonarCloud / CodeQL | Public JSON API only (no Why/How, no CodeQL — `gh` not installed) | `sie` CLI; produces Markdown report combining both |
| GitHub CLI | NOT available — sandbox can't auth | `gh`; PR checks, failed runs, Dependabot alerts |
| Deploy pipeline | `skills/delivery/scripts/prepare.sh` zips `download/` into `deliver.zip` | `scripts/unpack.sh` (double-click or terminal) → `skills/delivery/scripts/deploy.sh` (in bwrap sandbox) |

The pytest suite is small enough to run end-to-end in the sandbox (~182 specs, <1s, no network), and the user runs the same suite locally if they want a quick check. No Playwright/SSH server split — SIE is a pure Python script.

---
Scripts packaged in this skill

Six delivery scripts live at `skills/delivery/scripts/`; one user-side script lives at `scripts/` (the user entry point). `scripts/zip.sh` is self-contained (no `.base.sh` sourcing — the shared setup logic is folded in directly).

1. `prepare.sh` (sandbox-side, agent-run) — zips all loose files in `/home/z/my-project/download/` into `deliver.zip`, after touching `download/` to refresh the chat.z.ai "All files in task" widget. Removes loose files after zipping.

2. `deploy.sh` (template, included in `deliver.zip` unchanged) — deploys files from the extracted zip to the SIE repo via directory-walking `__` path reversal, then installs `sie.py` to `~/.local/bin/sie`, runs `uv sync`, sources the lint gate (Shellcheck + Ruff), runs the non-blocking SonarCloud exclusion-coverage check (`check_sonar_exclusions`), and runs `pytest`. The committed template lives at `skills/delivery/scripts/deploy.sh`.

3. `setup-sandbox.sh` (sandbox-side, one-time per session) — copies project skills from `skills/<name>/SKILL.md` into the chat.z.ai sandbox's `/home/z/my-project/skills/<name>/SKILL.md` so their `description` frontmatter auto-loads into the system prompt's `available_skills` list. Idempotent; re-run if the sandbox resets.

4. `lint_markdown.py` (sandbox-side, auto-run by `prepare.sh`) — auto-fixes bare `#identifier` / `[identifier]` outside backticks, normalizes bullet indentation to 4-space steps, auto-fixes `=== text ===` patterns, and warns about `[[wikilink]]` occurrences and bullet lines >400 chars. Skips YAML frontmatter, inline backtick spans, and fenced code blocks.

5. `split_bullets.py` (sandbox-side, manual run) — splits overlong bullet lines (>400 chars) at natural break points. Use when `lint_markdown.py` warns about overlong bullets.

The user-side `unpack.sh` lives at `scripts/unpack.sh` (not `skills/delivery/scripts/`) because it's the user entry point — discoverable at the repo's top-level `scripts/` folder, and double-clickable from a file manager (the script re-launches itself in a popup ghostty window when stdout is not a TTY) or run from a terminal. It runs `deploy.sh` inside a bwrap sandbox with `--clearenv`, read-only system paths, read-write repo root + `~/.local`, and read-only overlays on `.git/`, `archive/`, and `unpack.sh` itself.

`__` path encoding (for the deploy.sh directory-walking)

Files in `deliver.zip` use `__` (double underscore) as the path separator. Single hyphens in real filenames (e.g. `code-quality`, `input-forms`, `sonar-issue-exporter`) are preserved literally — `__` is unambiguous because no real filename or directory name in this project uses `__`. To decode: replace `__` with `/` to get the repo-relative path. Files with no `__` in their name (e.g. `sie.py`, `AGENTS.md`, `.gitignore`) are deployed to the repo root.

Examples:

| Flat name (in zip) | Repo-relative path (after decode) |
|---|---|
| `sie.py` | `sie.py` |
| `AGENTS.md` | `AGENTS.md` |
| `.gitignore` | `.gitignore` |
| `docs__input-forms.md` | `docs/input-forms.md` |
| `tests__test_url_parsing.py` | `tests/test_url_parsing.py` |
| `skills__code-quality__SKILL.md` | `skills/code-quality/SKILL.md` |
| `skills__delivery__scripts__deploy.sh` | `skills/delivery/scripts/deploy.sh` |
| `scripts__espanso.yml` | `scripts/espanso.yml` |
| `.omp__config.yml` | `.omp/config.yml` |

---
Workflow (high-level)

1. Only include files that CHANGED this turn. Files already deployed and unchanged will be skipped by `cmp -s` and waste the user's time (deploy.sh has to cmp each one, and the zip is inflated with unnecessary files). Only those + their dependencies go in `download/`.
2. Place all deliverables in `/home/z/my-project/download/` with flat `__`-encoded names (e.g. `skills__code-quality__SKILL.md`, not `skills/code-quality/SKILL.md`). See the encoding table above for the convention.
3. Place the committed `deploy.sh` in `download/` too (it gets included in the zip). The agent doesn't need to edit `deploy.sh` per session — the directory-walking approach derives the repo path from each flat filename automatically.
4. Run `bash skills/delivery/scripts/prepare.sh` (or wherever the sandbox-side copy lives). The script lints markdown, runs the lint gate (Shellcheck + Ruff), syntax-checks `sie.py` if present, zips everything into `deliver.zip`, touches `download/` to refresh the widget, uploads to tmpfiles.org as a fallback URL, and removes the loose files.
5. The user downloads `deliver.zip` (via the "All files in task" widget, or from the tmpfiles.org fallback URL printed by `prepare.sh`), double-clicks `scripts/unpack.sh` (or runs it from a terminal), which extracts, runs `deploy.sh` inside a bwrap sandbox, and cleans up.

---
Cautions and gotchas

- `download/` cleanliness: the same file should not exist both inside and outside the zip. After running `prepare.sh`, only `deliver.zip` should remain.
- Widget staleness: if the "All files in task" widget doesn't show `deliver.zip` after `prepare.sh` runs, `prepare.sh` touches `download/` to force a refresh. If the widget is still broken, upload `deliver.zip` to https://tmpfiles.org and paste the direct download link in chat.
- `deploy.sh` is a template: the committed copy at `skills/delivery/scripts/deploy.sh` is the reusable template. Each session, the agent includes the template inside `deliver.zip` unchanged — it auto-discovers files via the `__`-encoding walk, so no per-session edit is needed.
- Scoped cleanup: `unpack.sh` snapshots the zip's contents to `.deliver-files.list` before extraction. `deploy.sh`'s cleanup loop reads this manifest and only removes files that came from the zip — pre-existing `scratch/` files like `scratch.md` are NOT touched. Never use `find . -maxdepth 1 -type f` for cleanup; it sweeps pre-existing files.
- OMP skills symlinks: `.omp/skills/` contains a subset of symlinks to `../../skills/<name>`. Create them manually since the chat.z.ai sandbox blocks `ln -s`. OMP doesn't need all skills — it edits files directly, so delivery is not needed.

---
Cross-references

- `sonar-issue-exporter` — onboarding + workflow steps (Onboard, Code, Skills, Propose) + pre/post-patch checklists + post-turn updates + versioning. The brief download-folder rule there points here; this skill has the full deliver-zip protocol + naming convention.
- `code-quality` — patterns to follow and pitfalls to avoid when writing the bash delivery scripts (`set -euo pipefail`, `${var:?}` guards, scoped cleanup, no line continuations in quoted strings), plus the shared `lint_gate.sh` (Shellcheck + Ruff) sourced by `prepare.sh` and `deploy.sh`.
- `MEMORY.md` → "Deployment pipeline" — durable invariants: the `.deliver-files.list` cleanup scoping, the `--no-build` S8541 fix, the `scripts/unpack.sh` popup + bwrap sandbox.
- `scripts/README.md` — the per-script reference for the user-side scripts (`zip.sh`, `unpack.sh`, `diff-main.sh`) and the delivery scripts (this skill's scripts).
- `AGENTS.md` — minimal pointer that points to this skill and `sonar-issue-exporter` skill.
