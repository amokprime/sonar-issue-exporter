# sonar-issue-exporter — web chat agent instructions (chat.z.ai)

These are the agent project instructions, tailored for the chat.z.ai web-channel sandbox. Covers information that is not obvious from the provided Repomix archive.

## Repomix context — read these notes first

- Anything in `.gitignore` is dropped from the packed file contents, **but** the `<directory_structure>` tree summary still lists those paths. A path appearing in the tree does not guarantee its contents are in the pack — if the agent needs a file that isn't in the pack, ask the user to re-export or paste it.
- The tree is a snapshot at generation time; the live repo may have moved. When in doubt, confirm with the user.
- Binary files (images, screenshots) are never packed — only their paths appear in the tree.

## Project structure

- `/` — Project docs for humans (`README.md`, `LICENSE`). The README is the canonical user-facing doc; the `ai/chat.z.ai/` tree is for agents.
- `sie.py` — The single-file Python 3.10+ script (v1.0.0+). Zero third-party dependencies. Replaces the 0.2.x `export_sonar_issue.py` + `watch_clipboard.py` split.
- `sie-migrate.sh` — **Legacy.** Nondestructive migration script: uninstalls the old `uv tool` package, removes `~/.local/bin/sonar-export` and `~/.local/bin/sonar-watch` symlinks, installs `sie.py` as `~/.local/bin/sie`. Idempotent — safe to re-run. Superseded by `ai/chat.z.ai/scripts/delivery/deploy.sh` (which folds in all the migration logic plus the deploy + lint + test steps). Delete after adopting the `dsie` pipeline.
- `tests/` — Pytest suite covering URL parsing, GitHub URL → SonarCloud mapping, fuzzy input resolution, local-folder migration, CLI disambiguation, Markdown rendering, and output path resolution. Run with `uv run pytest tests/ -v` from the repo root. Pure unit tests — no network. See `tests/README.md` for the full design notes.
- `ai/chat.z.ai/` — This web chat workflow (the live copy).
  - `AGENTS.md` — This file.
  - `MEMORY.md` — Durable gotchas that don't survive refactor compaction. Lean — see the file's own header for the discipline rules.
  - `skill/` — Skill files (sonarqube-workflow, code-quality, skill, web-channel). Skills are re-read mid-session when context compacts; keep them under 500 lines each.
  - `scripts/` — The `dsie` deploy pipeline (`.base.sh`, `repomix.sh`, `zip.sh`, `delivery/prepare.sh`, `delivery/deploy.sh`, `delivery/unpack.sh`). See `scripts/README.md` for the per-script reference.
- `archive/` — AI chat transcripts for sie.py building sessions, plus Sonar issue exports under `archive/<version>/issues/`.

## Coding and testing

- Don't put large comment blocks in code files. Pair each non-trivial `name.ext` source file with a `name.md` readme explaining intent, usage, and known limitations. `sie.py` ↔ `README.md`; `sie-migrate.sh` ↔ the migration section in `README.md`.
- Documentation and context files should never be dense, minified walls of text. The `ai/chat.z.ai/` files are the exception — they're load-bearing for agent behavior — but they should still be skimmable.
- Fence code snippets in markdown documentation. Short inline references like `sie.py` or `sie -s` are fine as inline backticks; longer code fragments, URLs with query params, and multi-line examples should be fenced.

## Running the test suite

The pytest suite (`tests/`, ~112 specs) is lightweight — pure unit tests on parsing/resolution/rendering/output-path logic, no network. The sandbox can run it directly when a Repomix includes `sie.py` and `tests/**`:

```sh
# pytest is in .venv/ (installed via `uv sync`), not system-wide.
# Use `uv run` to invoke it:
uv run pytest tests/ -v
```

After patching `sie.py`, run `uv run pytest tests/` before declaring done. The test suite is the executable form of the code contracts documented in the skill files — if a test fails, the test name usually points to the function under test (e.g. `test_branch_with_slashes_in_name` → `sie.parse_github_url`).

When adding a new input form or output behavior, add a corresponding test in the matching file under `tests/`. See `tests/README.md` for the file-by-file coverage map. The agent can run this loop in-sandbox — no need to ask the user to reproduce test failures locally.

Network-dependent tests (live SonarCloud API calls, `gh pr list` invocations) are not yet in the suite — when the first one is needed, add `tests/test_network.py` with a `skipif` marker on `SIE_NETWORK_TESTS` env var so the default suite stays fast and sandbox-runnable.

## Linting

The project uses `ruff` (configured in `pyproject.toml`). Run from the repo root:

```sh
uv run ruff check --fix sie.py     # autofix safe violations before delivering
uv run ruff check sie.py           # gate — fails on any remaining violation
```

The line-length is 100, matching the 0.2.x convention. The rule set is `E,W,F,I,C90,UP,B` — pycodestyle errors/warnings, pyflakes, isort, mccabe complexity (default threshold 10), pyupgrade, flake8-bugbear. C901 (mccabe) and SonarCloud's S3776 (cognitive, threshold 15) measure different things — both are intentionally enabled; a function that exceeds EITHER metric warrants a refactor.

The deploy pipeline (`dsie`) runs `ruff check --fix` + `ruff check` as a gate, so any unfixed violations abort the deploy on the user's machine. Pre-linting in-sandbox before delivering avoids that — the agent should always run `ruff check --fix sie.py` before declaring a patch done.

## SonarCloud

- The project is public — the sandbox can enumerate open issues directly via the JSON API (no auth needed for issue enumeration, facets, and pagination). Use Python `urllib` (not the web reader tool — its URL validator rejects some query strings and the SPA pages render nothing for a static reader).
  - Main branch: `https://sonarcloud.io/api/issues/search?componentKeys=amokprime_sonar-issue-exporter&issueStatuses=OPEN`
  - PR staging: `https://sonarcloud.io/api/issues/search?componentKeys=amokprime_sonar-issue-exporter&pullRequest=N&issueStatuses=OPEN`
- The agent can triage directly from the returned JSON — no need for the user to export and upload. See the `sonarqube-workflow` skill for the full sandbox API protocol (facets for first-pass counts, rule filtering, pagination, the auth-required endpoints to avoid).
- **Auth boundary**: issue enumeration, facets, and rule filtering work unauthenticated. Rule metadata (`api/rules/show` — the `why`/`how` content) and single-issue lookup by key require auth — for rule rationale, the user runs `sie '<URL>'` locally with `SONAR_API_KEY` set and uploads the resulting Markdown.
- Exported issue Markdown (when the user does run `sie` locally) is a single file at `scratch/sonar-issues.md` or `./sonar-issues.md` (depending on CWD context), not the per-issue folder tree of 0.2.x. See the `sonarqube-workflow` skill for the new layout.
- **Gotcha**: closed issues have `line: null` in the API response (and appear as `Lunknown.json` in 0.2.x local exports) — check `status`/`resolution` before triaging, since closed issues can masquerade as fresh findings. The Markdown renderer marks these with `Lunknown` in the Line column.

## Delivery workflow

The `dsie` fish abbreviation (`abbr --add dsie '~/GitHub/sonar-issue-exporter/ai/chat.z.ai/scripts/delivery/unpack.sh'`) is the user's one-command deploy. The agent's per-turn obligations (mirroring LineByLine's `project-workflow-SKILL.md`, scoped to sonar-issue-exporter):

### Pre-patch checklist

1. Stop and request clarification when: a request is unclear, relevant files are missing from the Repomix, a request is technically infeasible, or a request violates a skill.
2. Read only the sections you need — `sie.py` is ~2000 lines; grep for function names (`def parse_url_input`, `def render_markdown`, `def main`) and read just those ranges instead of the whole file.
3. Patch with minimal diff — change only what's needed and preserve surrounding code. Prefer targeted edits over full-section rewrites unless the section is being restructured.
4. Consult `code-quality-SKILL.md` before modifying functions in `sie.py` (cognitive complexity threshold 15, redundant-exception-class gotcha, mutable defaults, KEEP_FIELDS ordering, URL-parsing param passthrough, GitHub branch-slash handling, CLI disambiguation).

### Post-patch verification

1. **Syntax check** — `python3 -c "import py_compile; py_compile.compile('sie.py', doraise=True)"` or `uv run python -c "import sie"`. A syntax error in `sie.py` means the entire script is broken.
2. **Lint** — `uv run ruff check --fix sie.py && uv run ruff check sie.py`. The deploy pipeline gates on this; pre-linting in-sandbox avoids the gate failing on the user's machine.
3. **Tests** — `uv run pytest tests/ -v`. The test suite is the executable form of the code contracts in the skill files — if a test fails, the test name usually points to the function under test.
4. **Trace one user action** — if the patch changed any logic (not just formatting), trace one user action through the changed code path to confirm it reaches the expected outcome.

### Post-turn updates

Apply after every turn, regardless of whether a code patch was made. The user may push at any moment without notifying the agent — documentation artifacts must already be current.

1. **MEMORY.md** — update when a turn produces a durable fact (gotcha, invariant, project-specific constraint that training data wouldn't predict). Apply the update inline (deliver the updated `MEMORY.md` in `download/`). Don't propose as a draft for the user to approve. If the turn produces nothing distinctive, skip this.
2. **Skills** — update when a patch changes the architecture a skill documents (e.g. extracting a function changes `code-quality-SKILL.md`'s reference to it; adding a new CLI flag changes `sonarqube-workflow-SKILL.md`'s input-forms reference). Don't update for a pure bug fix that doesn't change the documented architecture. Apply updates inline.
3. **Download copy** — copy only the files created or updated this turn to `download/` with flat hyphenated names (e.g. `ai/chat.z.ai/MEMORY.md` → `ai-chat.z.ai-MEMORY.md`). Then run `prepare.sh` to zip into `deliver.zip` and remove the loose files (only `deliver.zip` should remain). The user downloads the zip, not the individual files.

### Script architecture (for agents modifying the scripts)

The upload scripts (`repomix.sh`, `zip.sh`) source `.base.sh` and define a `snippet()` function with the workflow-specific command. `.base.sh` handles the shared setup (path resolution, scratch/upload dir, zip + clipboard). This mirrors LineByLine's `.base.sh` pattern. When adding a new upload workflow, define a new `snippet()` and source `.base.sh` — don't duplicate the setup logic.

The delivery scripts (`prepare.sh`, `deploy.sh`, `unpack.sh`) don't source `.base.sh` — they're a different workflow (deploy, not upload) and have their own shared variables (`DEST`, `SCRATCH`, `SIE_BIN`).

### Cleanup safety (deploy.sh)

`deploy.sh`'s collision-cleanup at the end is scoped to only the files that came from `deliver.zip` — `unpack.sh` writes a `.deliver-files.list` manifest before extraction, and `deploy.sh` reads it to know which files to remove. Pre-existing files in `scratch/` (notes, prior session zips, anything the user stashed there) are preserved. A prior version used `find . -maxdepth 1 -type f` and swept every file in `scratch/`, deleting a user's `scratch.md` notes — see `archive/1.0.0/bug.md` for the post-mortem. If you ever modify the cleanup phase, preserve the manifest-based scoping.