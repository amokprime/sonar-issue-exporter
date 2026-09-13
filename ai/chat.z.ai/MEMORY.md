# sonar-issue-exporter — durable memory seed

Harness-agnostic, git-tracked memory for AI coding agents. When a turn produces a durable fact (gotcha, invariant, project-specific constraint that training data wouldn't predict), update this file. The web-channel agent edits its sandbox copy and produces it in `download/` for the user to apply to the repo.

**Discipline**: keep this lean. One-off gotchas that could harm the project now or in the very near future belong here. Historical lessons that don't survive the most recent refactor should be compacted to a one-line reference (or pruned if totally harmless). If a class of knowledge recurs across versions, promote it to a skill in `ai/chat.z.ai/skill/` and leave a one-line pointer here.

## IM gateway: README name + persistence bugs

- **`README.md` (exact name) doesn't show up in the chat download list.** A loose `README.md` placed in `download/` is invisible to the user — they see other loose files but not `README.md`. The fix: bundle it inside `deliver.zip` (the zip's internal filename doesn't trigger the filter). This is why the deliver workflow is preferred for any turn that ships a `README.md` change, even pure-docs updates — `prepare.sh` → `deliver.zip` → `dsie` gets around the bug.
- **Files once introduced to `download/` persist in the user's view even after the agent removes them from the sandbox.** Removing a stale `deliver.zip` from `download/` doesn't make it disappear from the chat's file list — the IM gateway caches the listing. Don't try to "clean up" the user's view by `rm`-ing old files; just produce a fresh `deliver.zip` and the user will grab the latest one.

## Repomix extraction: leading empty line breaks shebangs (v1.1.0 bug)

The repomix XML format puts a newline between `<file path="...">` and the file content. When extracting with `re.compile(r'<file path="([^"]+)">(.*?)</file>', re.DOTALL)`, the captured content starts with `\n` — so every extracted file has an empty line 1. For most files this is harmless (Markdown, TOML, Python tests imported as modules). But for **executable scripts** (`sie.py`, shell scripts with shebangs), it's fatal: the kernel's shebang processing only reads line 1, so an empty line 1 means no interpreter is found, and the shell falls back to `/bin/sh` — which tries to parse the Python/shell file as shell commands and fails spectacularly.

**v1.1.0 postmortem**: `sie.py` was deployed with an empty line 1 (inherited from the repomix extraction). `~/.local/bin/sie` became unexecutable — `sie --version` printed the module docstring as shell commands and hung. The deploy.sh `sie --version` check (under `set -e`) aborted the deploy before reaching `uv sync` + `ruff` + `pytest`, so the test suite never ran. The fix: strip the leading empty line from `sie.py` (and all shipped files) before staging to `download/`.

**Pre-delivery check**: after staging files, verify `head -1 sie.py` prints `#!/usr/bin/env python3` (not empty). The test suite does NOT catch this — tests import `sie` as a module. Only `chmod +x sie.py && ./sie.py --version` catches it. This check is step 4 of the AGENTS.md post-patch verification checklist.

**Extraction fix**: when re-extracting from repomix.xml, strip the leading `\n` from every file: `content = content[1:] if content.startswith("\n") else content`.

## Test environment-dependency: `~/Downloads` existence (v1.1.0 bug)

`_resolve_default_output_dir(cwd)` has a last-resort branch: if `cwd` isn't in a git project, it returns `~/Downloads` if that directory exists, else falls back to `cwd`. This means tests that call `export_url(..., output_path=None, cwd=tmp_path)` and assert the file landed in `tmp_path` are **environment-dependent**: they pass on sandboxes where `~/Downloads` doesn't exist but fail on user machines where it does.

**Fix**: create `(tmp_path / ".git").mkdir()` at the start of any test that calls `export_url` with `output_path=None`, OR pass an explicit `output_path=str(tmp_path / "out.md")`.

## SonarCloud project key

The SonarCloud project key is `amokprime_sonar-issue-exporter` (not `sonar-issue-exporter`). Derived from the GitHub `owner/repo` as `<owner>_<repo>` — the SonarCloud convention for GitHub-integrated projects. `sie`'s fuzzy and GitHub-URL input forms auto-derive this; only custom project keys need an explicit SonarCloud URL.

## Auth boundary

See `sonarqube-workflow-SKILL.md` Step 0 for the canonical auth boundary table (what works unauthenticated vs. what requires `SONAR_API_KEY`). The key points: issue enumeration/facets/pagination work unauthenticated; `api/rules/show` (why/how content) and single-issue `?issues=<KEY>` lookup require auth.

## API key: env var only (no .env)

`sie` reads the API key exclusively from environment variables — no `.env` file support. `get_token()` checks `SONAR_API_KEY` first (preferred), then `SONAR_TOKEN` (SonarQube convention fallback). The 0.2.x `BEARER_TOKEN` env var and `~/.env` file are no longer read.

## Token visibility gotcha (fish + KWallet)

If `sie` reports "Token: absent" but the user believes the env var is set, the most likely cause is that `kwallet-query` returned an empty string at shell-startup time because KWallet was locked. `sie -d` (or `sie --debug-env`) prints the status of each candidate env var: not set / set but empty / set with N chars. Fix: re-run the `set -gx` line after unlocking KWallet, or restart the shell.

## Output path priority

See `docs/output-paths.md` for the canonical resolution rules. Summary: `scratch/` (git root) → cwd (git root, no scratch) → cwd (git non-root) → `~/Downloads/` (last resort). Default filename is `issues.md` (v1.1.0: renamed from `sonar-issues.md`). For `sie -m` (migration), output defaults to alongside the issues folder.

## `pr` shortcut requires `gh`

The `sie pr` single-token shortcut invokes `gh pr list --state open --limit 1` to find the most recent open PR. Without `gh` on PATH, it errors with a helpful message — it does NOT silently fall back. In a chat.z.ai sandbox, `gh` is typically not installed; use the explicit GitHub PR URL form instead.

## Local-path disambiguation + `-m` auto-discovery

See `code-quality-SKILL.md` "Local-path disambiguation" section for the canonical contract: a single path-like positional is the OUTPUT path (input defaults to main of CWD's repo), NOT a migration input. Migration requires `-m`.

`-m` auto-discovery: if CWD contains an `issues/` subfolder that looks like a 0.2.x export → migrate that; if CWD itself looks like an issues folder → migrate CWD. Safety refusals: `.git/` in CWD, or existing `issues.md` in the output directory.

## Closed-issue gotcha

See `sonarqube-workflow-SKILL.md` Step 0 for the canonical description. Closed issues have `line: null` in the API response and render with `Lunknown` in the Line column. Check `status` before triaging — a closed/FIXED issue in a fresh export is stale, not a regression.

## Field ordering (KEEP_FIELDS)

See `code-quality-SKILL.md` "Field ordering (KEEP_FIELDS)" section for the canonical contract. The order is `rule, component, line, textRange, message, severity, type, cleanCodeAttribute, cleanCodeAttributeCategory, impacts, flows` (identity → location → description → classification → evidence). Don't reorder without reason.

## CLI flags + clean mode

Every longform flag has a shortform: `-h/--help`, `-s/--summary`, `-m/--migrate`, `-d/--debug-env`, `-c/--clean`, `-v/--version`. See `README.md` and `docs/clean-mode.md` for details. Clean mode (`-c`) silently drops Why/How sections to avoid pushing licensed Sonar content.

## Deployment pipeline (replaces sie-migrate.sh)

The `dsie` fish abbreviation runs `ai/chat.z.ai/scripts/delivery/unpack.sh` which extracts `deliver.zip` to `scratch/`, runs `deploy.sh` (deploys files, installs `sie.py` to `~/.local/bin/sie`, cleans 0.2.x artifacts, runs `uv sync` + ruff gate + pytest), then cleans up. See `scripts/README.md` for the per-script reference.

**Ruff gate**: deploy.sh aborts if `ruff check sie.py` fails after `ruff check --fix`. Pre-lint in-sandbox before delivering.

**Cleanup safety**: `deploy.sh`'s collision-cleanup is scoped to only files from `deliver.zip` (per a `.deliver-files.list` manifest). Never use `find . -maxdepth 1 -type f` for the cleanup — it sweeps pre-existing files. See `archive/1.0.0/1.0.0.md` for the post-mortem on the two prior `find .` regressions.

## `uv sync` for dev deps

Dev dependencies (pytest, ruff) are in `pyproject.toml`'s `[project.optional-dependencies] dev = [...]`. Install with `uv sync --extra dev` (not `pip install -e ".[dev]"`). `uv sync` is idempotent. `uv run pytest tests/ -v` invokes pytest using the venv's Python.

## What training shadows (flag for the agent)

- **SonarCloud vs SonarQube**: `sie` is hardcoded to `https://sonarcloud.io` and won't work against self-hosted SonarQube without code changes.
- **`uv tool install`**: for `sie` 1.0.0+, the install is `install -Dm755 sie.py ~/.local/bin/sie` — no build step, no venv. The `uv tool` route is only for the legacy 0.2.x install.
- **`pyperclip`**: `sie` 1.0.0+ dropped clipboard watching entirely. Don't suggest adding it back.
- **`html2text`**: `sie` uses a crude stdlib-only HTML stripper. Don't suggest `html2text` unless the user reports actual rendering issues.
- **`.env` files**: `sie` reads the API key exclusively from environment variables. Don't suggest `.env` as an alternative.

## Cognitive-complexity reduction passes (v1.0.0 + v1.1.0)

`render_markdown`, `parse_local_export`, `discover_repo`, `export_url`, and `_print_summary_stdout` were refactored to bring their cognitive complexity under the S3776 threshold (15) by extracting helpers. See `code-quality-SKILL.md` for the reduction techniques and the v1.0.0/v1.1.0 helper lists.

## GitHub CodeQL `py/incomplete-url-substring-sanitization` (fixed v1.0.0)

CodeQL flagged `resolve_input` for substring checks on unparsed URLs (`"sonarcloud.io" in raw`). The fix: dispatch on `urllib.parse.urlparse(raw).netloc`, not substring matching. Tests: `tests/test_input_resolver.py::test_url_with_evil_host_embedded_in_path_does_not_bypass_dispatch`.

## GitHub code-scanning URL form (`/security/code-scanning/<N>`)

`sie` accepts `https://github.com/owner/repo/security/code-scanning/<N>` URLs — fetches a single GitHub code-scanning alert via `gh api`. The descriptor carries a `code_scanning_alert` field so `export_url` routes to `_run_code_scanning_mode` (not the SonarCloud pipeline). Synthetic key is `codeql:<alert_number>`. This is the v1.0.0 single-alert URL form; the v1.1.0 auto-discovery (below) is the new default.

## v1.1.0: CodeQL auto-discovery + merged output

`sie`, `sie staging`, and `sie pr` now fetch repo-wide open CodeQL alerts alongside the branch-scoped SonarCloud issues. The two sources render into a single `issues.md` with `## SonarCloud Issues` and `## CodeQL Alerts` sections. If `gh` is unavailable, the CodeQL capability is silently dropped. If both sources are empty, no file is written.

Key functions: `fetch_open_code_scanning_alerts` (silent-drop `gh api --paginate`), `_is_sonar_pushed_alert` (dedup by `tool.name` containing "sonar"), `_code_scanning_alerts_to_issues`, `_fetch_code_scanning_for_project` (entry point), `render_combined_markdown` (merged renderer with demoted headings), `_render_export_markdown` (three-way dispatch: both/sonar-only/codeql-only/empty).

Output filename renamed: `DEFAULT_OUTPUT_NAME` is now `issues.md` (was `sonar-issues.md`). Summary mode (`-s`) also includes a `CodeQL Alerts: N open` line.

Dedup design: `tool.name` matching only (no tuple-based `(rule, path, line)` matching). `tool.name` is canonical — SonarCloud-pushed alerts have `tool.name = "SonarCloud"` or `"SonarQube"`, native CodeQL has `tool.name = "CodeQL"`. O(n), robust to line drift, no false positives.

## Versioning

Patch releases (1.0.0 → 1.0.1) for bug fixes. Minor bumps (1.0.x → 1.1.0) for new features that change the CLI surface or output format. Major bumps (1.x.y → 2.0.0) for breaking changes. The version is hardcoded at the top of `sie.py` as `VERSION = "1.1.0"` — update in lockstep with `pyproject.toml` and `README.md`.
