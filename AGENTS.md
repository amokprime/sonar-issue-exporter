# sonar-issue-exporter — project agent instructions

This file is a minimal pointer. Most agent-facing context lives in skills under `skills/` (auto-loaded into `available_skills` via `skills/delivery/scripts/setup-sandbox.sh`) and in `MEMORY.md`. If you're a fresh agent looking for onboarding, workflow, or project structure details, invoke `Skill(command="sonar-issue-exporter")` for onboarding + workflow, and `Skill(command="delivery")` for web-channel rules + the delivery workflow.

## Why this file is minimal

Many projects put project structure, coding rules, test-running instructions, sandbox environment details, and consolidation direction in AGENTS.md. This project offloads those to skills instead, because the chat.z.ai sandbox auto-loads skill descriptions into the system prompt's `available_skills` list — skills are invokable on-demand without an explicit Read, and their descriptions surface proactively when the task matches. A bare AGENTS.md cannot do this; it must be Read explicitly every turn.

What would normally live here, and where it actually lives:

- **Onboarding + workflow** (steps, pre/post-patch checklists, versioning, deliver-zip pointer) → `sonar-issue-exporter` skill (`Skill(command="sonar-issue-exporter")`)
- **Web channel behavioral rules + delivery workflow** (file visibility, input handling, output format, comment density, prepare → zip → deploy pipeline) → `delivery` skill (`Skill(command="delivery")`). The delivery scripts live at `skills/delivery/scripts/`.
- **SonarCloud & CodeQL** (`sie` report, sandbox API fallback) → `sonarqube-workflow` skill
- **Code quality patterns** (cognitive complexity, redundant exceptions, mutable defaults, KEEP_FIELDS, URL parsing, bash script patterns) → `code-quality` skill
- **Consolidation direction** (skill vs. MEMORY.md) → `skill` skill
- **Linting** → `ruff check sie.py` (configured in `pyproject.toml`); the deploy pipeline gates on it

## Project structure

- `/` — Project docs for humans (`README.md`, `CONTRIBUTING.md`, `LICENSE`, `AGENTS.md`, `MEMORY.md`). The README is the canonical user-facing doc; the agent-facing tree is `skills/`, `scripts/`, `.omp/`, `ai/`.
- `sie.py` — The single-file Python 3.10+ script (v1.1.0+). Zero third-party dependencies.
- `tests/` — Pytest suite (~182 specs) covering URL parsing, GitHub URL → SonarCloud mapping, fuzzy input resolution, local-folder migration, CLI disambiguation, Markdown rendering, and output path resolution. Pure unit tests — no network. Run with `uv run pytest tests/ -v` from the repo root. See `tests/README.md` for the file-by-file coverage map.
- `docs/` — User-facing docs split out of the README for skimmability: `input-forms.md`, `output-paths.md`, `clean-mode.md`, `auth-boundary.md`, `troubleshooting-token.md`.
- `skills/` — Project skills (auto-load via `skills/delivery/scripts/setup-sandbox.sh`). Each skill lives at `skills/<name>/SKILL.md` with optional co-located `scripts/` (e.g. `skills/delivery/scripts/prepare.sh`, `skills/delivery/scripts/deploy.sh`, `skills/delivery/scripts/setup-sandbox.sh`).
- `scripts/` — `zip.sh` (ad-hoc zip utility, self-contained),
    - `unpack.sh` (user-side deploy wrapper — double-click in a file manager or run from a terminal; re-launches itself in a popup ghostty window on non-TTY stdout, runs `deploy.sh` inside a bwrap sandbox),
    - `diff-main.sh` (capture local uncommitted state as a patch + metadata for AI agent reproduction),
    - `espanso.yml` (Espanso snippets for OMP sessions — hardlink to `~/.config/espanso/match/sonar-issue-exporter.yml`), and `README.md`.
- `.omp/` — OMP harness scaffolding for the local Copilot-like OMP agent (DeepSeek V4.1 Flash via Token Harbor, or any free API provider you configure). Contains `config.yml` (memory backend: Sharpshooter, autolearn enabled), `AGENTS.md` + `RULES.md` (OMP-specific project context), and `skills/` (relative symlinks to `../../skills/<name>` so OMP auto-loads the same skills as chat.z.ai).
- `ai/` — Human-facing reference docs for the chat.z.ai web-channel workflow: `README.md` (chat.z.ai caveats + Espanso snippet list for OMP), `templates/` (blank Obsidian transcript templates for archiving chat sessions — `chat.z.ai.md` and `OMP.md`).
- `archive/` — AI chat transcripts for `sie.py` building sessions, plus Sonar issue exports under `archive/<version>/issues/`. Versions: 0.1.0, 0.1.1, 0.1.2, 0.2.0–0.2.2, 1.0.0, 1.1.0.
- `scratch/` — gitignored scratch directory. The user may draft prompts at `scratch/scratch.md` — do not save files at that name (collision).

## Getting started

1. Clone the main branch: `git clone --branch main https://github.com/amokprime/sonar-issue-exporter.git` (this project pushes directly to `main`, not a staging branch).
2. Run `bash skills/delivery/scripts/setup-sandbox.sh` to install project skills into the chat.z.ai sandbox's `available_skills`.
3. Invoke `Skill(command="sonar-issue-exporter")` for onboarding, workflow, web-channel rules, and the delivery workflow.
4. Read `MEMORY.md` for durable gotchas and project invariants.
5. Use the Espanso snippets in `scripts/espanso.yml` (`:scm`, `:sco`, `:ssk` triggers) for step-specific context loading. See `ai/README.md` for the current trigger list.
