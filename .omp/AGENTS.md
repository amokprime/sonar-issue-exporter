The front-facing context files in this repo are designed for a cloud sandbox agent (chat.z.ai) that builds and tests most code. You (the OMP agent) will work with the existing local checkout of the same repo (`~/GitHub/sonar-issue-exporter/`, literally this project) for relatively lightweight tasks such as:
- Troubleshooting bugs that cannot be reproduced in the cloud sandbox (i.e. due to a local environment quirk). Usually this involves the delivery scripts or `sie.py`'s local-shell integration (KWallet token visibility, `gh` auth, output path resolution against real CWD).
- Patching SonarCloud issues when the chat.z.ai session is 15+ turns in.
- Updating stale documentation or agent context files (this refactor session is one example).
- Pre-screening `sie.py` changes before pushing them to chat.z.ai for a full build/test/review pass.

Therefore, you have your own context files, sandbox rules, and a subset of relevant skills.

### Project structure
- `/` — Project docs for humans (`README.md`, `CONTRIBUTING.md`, `LICENSE`, `AGENTS.md`, `MEMORY.md`). Evaluate for stale references when the relevant area changes.
- `sie.py` — The single-file Python 3.10+ script. Zero third-party dependencies. This is the canonical file you'll patch.
- `tests/` — Pytest suite (~182 specs). Pure unit tests, no network. Run with `uv run pytest tests/ -v` from the repo root.
- `docs/` — User-facing docs split out of the README for skimmability: `input-forms.md`, `output-paths.md`, `clean-mode.md`, `auth-boundary.md`, `troubleshooting-token.md`.
- `skills/` — The cloud agent's skill folder. Each skill lives at `skills/<name>/SKILL.md`:
    - `skills/sonar-issue-exporter/` — onboarding + workflow (the project skill — chat.z.ai's primary reference)
    - `skills/delivery/` — web-channel behavioral rules + delivery workflow (prepare → zip → deploy), plus the delivery scripts at `skills/delivery/scripts/`
    - `skills/code-quality/` — Python + bash code quality patterns (CC reduction, redundant exception classes, mutable defaults, KEEP_FIELDS, URL parsing, bash script patterns for the delivery scripts)
    - `skills/sonarqube-workflow/` — `sie` Markdown report triage + sandbox API fallback + SonarCloud/CodeQL environment details
    - `skills/skill/` — when to create or update skills vs `MEMORY.md` entries; consolidation direction protocol
    - `skills/delivery/scripts/` — delivery pipeline scripts (prepare.sh, deploy.sh, setup-sandbox.sh, setup-omp-skills.sh)
- `scripts/` — user-side scripts: `zip.sh` (ad-hoc zip, self-contained), `unpack.sh` (user-side deploy wrapper — double-click or run from a terminal; popup ghostty + bwrap sandbox), `diff-main.sh` (capture local uncommitted state for chat.z.ai agent reproduction), `espanso.yml` (Espanso snippets — hardlink to `~/.config/espanso/match/sonar-issue-exporter.yml`), `README.md`.
- `.omp/` — your scaffolding: `config.yml` (memory backend: Sharpshooter, autolearn enabled), `AGENTS.md` (this file), `RULES.md` (OMP-specific coding rules), `skills/` (relative symlinks to `../../skills/<name>` so you auto-load the same skills as chat.z.ai — see `setup-omp-skills.sh`).
- `ai/` — Human-facing reference docs for the chat.z.ai web-channel workflow: `README.md` (chat.z.ai caveats + Espanso trigger list), `templates/` (blank transcript templates — `chat.z.ai.md`, `OMP.md`).
- `archive/` — AI chat transcripts per version (0.1.0, 0.1.1, 0.1.2, 0.2.0–0.2.2, 1.0.0, 1.1.0) plus Sonar issue exports under `archive/<version>/issues/`. Read these only if directly relevant to the current task.
- `scratch/` — gitignored scratch directory. The user may draft prompts at `scratch/scratch.md` — do not save files at that name (collision).

### Environment
- Repo root: `~/GitHub/sonar-issue-exporter` (override via `SONAR_ISSUE_EXPORTER_ROOT`).
- This project pushes directly to `main` (no staging branch). Don't push for the user — they push themselves after reviewing your patch.
- Tests: `uv run pytest tests/ -v` runs the full suite in <1s. The sandbox runs the same suite.
- Lint: `uv run ruff check --fix sie.py && uv run ruff check sie.py` (the deploy pipeline gates on this).
- `gh` is available locally; `sie pr` works (finds the most recent open PR via `gh pr list`).
- `SONAR_API_KEY` (or `SONAR_TOKEN`) env var: needed for the `why`/`how` rule rationale (`api/rules/show`); public-project issue enumeration works without it.
