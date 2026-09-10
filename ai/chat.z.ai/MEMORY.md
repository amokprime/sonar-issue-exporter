# sonar-issue-exporter — durable memory seed

Harness-agnostic, git-tracked memory for AI coding agents. When a turn produces a durable fact (gotcha, invariant, project-specific constraint that training data wouldn't predict), update this file. The web-channel agent edits its sandbox copy and produces it in `download/` for the user to apply to the repo.

**Discipline**: keep this lean. One-off gotchas that could harm the project now or in the very near future belong here. Historical lessons that don't survive the most recent refactor should be compacted to a one-line reference (or pruned if totally harmless). If a class of knowledge recurs across versions, promote it to a skill in `ai/chat.z.ai/skill/` and leave a one-line pointer here.

## IM gateway: README name + persistence bugs

- **`README.md` (exact name) doesn't show up in the chat download list.** A loose `README.md` placed in `download/` is invisible to the user — they see other loose files but not `README.md`. The fix: bundle it inside `deliver.zip` (the zip's internal filename doesn't trigger the filter). This is why the deliver workflow is preferred for any turn that ships a `README.md` change, even pure-docs updates — `prepare.sh` → `deliver.zip` → `dsie` gets around the bug.
- **Files once introduced to `download/` persist in the user's view even after the agent removes them from the sandbox.** Removing a stale `deliver.zip` from `download/` doesn't make it disappear from the chat's file list — the IM gateway caches the listing. Don't try to "clean up" the user's view by `rm`-ing old files; just produce a fresh `deliver.zip` and the user will grab the latest one.

## SonarCloud project key

The SonarCloud project key is `amokprime_sonar-issue-exporter` (not `sonar-issue-exporter`). Derived from the GitHub `owner/repo` as `<owner>_<repo>` — the SonarCloud convention for GitHub-integrated projects. `sie`'s fuzzy and GitHub-URL input forms auto-derive this; only custom project keys need an explicit SonarCloud URL.

## Auth boundary (verified Sep 2026)

- Issue enumeration (`api/issues/search`): works unauthenticated for public projects.
- Facets (`api/issues/search?facets=...`): works unauthenticated.
- Pagination (`&p=N&ps=500`): works unauthenticated.
- Rule metadata (`api/rules/show`): **requires auth** + the `organization` query param. Without `organization`, returns HTTP 400 with `{"errors":[{"msg":"The 'organization' parameter is missing"}]}`.
- Single-issue lookup (`api/issues/search?issues=<KEY>`): **requires auth**. Without it, returns 0 issues (not an error — just an empty result that's easy to misread as "issue doesn't exist").

`sie` extracts the `organization` field from the issue JSON returned by the search call, then passes it to the subsequent `api/rules/show` call. If the user runs `sie` without `SONAR_API_KEY`, the why/how sections render placeholders pointing to the env var — issue enumeration still works.

## API key: env var only (no .env)

`sie` 1.0.0+ reads the API key exclusively from environment variables — no `.env` file support. The user's setup (fish shell + KDE Wallet):

```fish
# ~/.config/fish/config.fish
set -gx SONAR_API_KEY (kwallet-query -f ksshaskpass -r Sonar kdewallet | string trim)
```

`sie.get_token()` checks `SONAR_API_KEY` first (user's preference), then `SONAR_TOKEN` (SonarQube convention fallback). The 0.2.x `BEARER_TOKEN` env var and `~/.env` file are no longer read — users who configured 0.2.x with `~/.env` need to migrate to the shell-env-var approach. The `sie-migrate.sh` script doesn't handle this migration; the user does it manually by adding the `set -gx` line to their shell rc.

## Token visibility gotcha (fish + KWallet)

If `sie` reports "Token: absent" but the user believes the env var is set, the most likely cause is that `kwallet-query` returned an empty string at shell-startup time because KWallet was locked. The `set -gx` line runs at shell startup; if KWallet isn't unlocked yet, `kwallet-query` fails silently and the var is set to `""`. Fish's `set -q -x SONAR_API_KEY` exits 0 (var is set+exported) and `string length $SONAR_API_KEY` prints `0` — but `0` is easy to miss in the output.

**Diagnostic**: `sie -d` (or `sie --debug-env`) prints the status of each candidate env var: not set / set but empty / set with N chars. This distinguishes the three cases and points to the likely cause.

**Fix**: re-run the `set -gx` line after unlocking KWallet, or restart the fish shell. For persistent fix, ensure KWallet auto-unlocks on login (KDE Wallet settings → "When the wallet is opened, automatically unlock all wallets" or PAM integration via `kwallet-pam`).

Note: the user has two SonarCloud tokens in their account — `ISSUES_TOOL` (saved as "Sonar" in KWallet, queried via `kwallet-query -f ksshaskpass -r Sonar`) and `SONAR_TOKEN` (a separate token used previously). `sie`'s `get_token()` checks `SONAR_API_KEY` first (which holds the `ISSUES_TOOL` value via KWallet), then falls back to `SONAR_TOKEN`. If both env vars are unset/empty, `sie` reports "absent" even though issue enumeration still works for public projects.

## Output path priority

`sie` resolves the default output directory (when no explicit output path is given) in this order:

1. **`scratch/`** if CWD is a git root and `scratch/` exists
2. **CWD** if CWD is a git root without `scratch/`
3. **CWD** if inside a git project but not at root
4. **`~/Downloads/`** (last resort) if not in a git project

This replaces the 0.2.x `~/Downloads` default and the 1.0.0-alpha `~/Downloads` default. The `scratch/` preference avoids cluttering the project root; the git-non-root case lets the user write alongside wherever they are (e.g. inside `archive/0.2.0/`); the last-resort `~/Downloads` matches the old default for users not in a git repo.

For `sie -m` (migration), the output defaults to alongside the issues folder (`<folder_parent>/sonar-issues.md`), not the git-aware path — the migration output belongs next to the input.

## `pr` shortcut requires `gh`

The `sie pr` single-token shortcut invokes `gh pr list --state open --limit 1 --json number,headRefName,title` to find the most recent open PR. Without `gh` on PATH, it errors with a helpful message pointing to https://cli.github.com — it does NOT silently fall back to "no PR found". In a chat.z.ai sandbox, `gh` is typically not installed; the agent should use the explicit GitHub PR URL form (`sie -s 'https://github.com/owner/repo/pull/N'`) instead.

## Local-path disambiguation

`sie` treats a single path-like positional (`/abs`, `~/...`, `./...`, `../...`, `C:\...`) as the OUTPUT path with input defaulting to main of CWD's repo — NOT as a migration input. Local-folder migration requires the `-m` flag. This was added in v1.0.0 to resolve the ambiguity where `sie ~/report.md` from project root could have been misinterpreted as "migrate the folder at ~/report.md".

The `resolve_input()` function explicitly raises `ValueError` on path-like inputs — this is intentional, not a bug. The CLI layer in `main()` catches path-like positionals BEFORE calling `resolve_input`, routing them to the output-path-only path or the `-m` path as appropriate.

## `-m` auto-discovery

`sie -m` without an explicit path auto-discovers the issues folder:
1. If CWD contains an `issues/` subfolder that looks like a 0.2.x export (has subdirs with `L*.json` files) → migrate `cwd/issues/`, output to `cwd/`
2. If CWD itself looks like an issues folder → migrate `cwd/`, output to `cwd.parent/`
3. Else → error with helpful message

Safety refusals:
- `.git/` in CWD (auto-discovery at a git root is too risky)
- Existing `sonar-issues.md` in the output directory (don't clobber)

## Closed-issue gotcha (carried from 0.2.x)

Closed issues have `line: null` in the SonarCloud API response. In 0.2.x local exports, these appeared as `Lunknown.json` files. In 1.0.0's Markdown output, they render with `Lunknown` in the Line column. The `status` field is the source of truth — a closed/FIXED issue in a fresh export is stale, not a regression. Don't triage closed issues as new findings.

## Field ordering (KEEP_FIELDS)

The 0.2.x `export_sonar_issue.py` established a specific field order for the per-issue JSON: `rule, component, line, textRange, message, severity, type, cleanCodeAttribute, cleanCodeAttributeCategory, impacts, flows` (identity → location → description → classification → multi-line evidence). The 1.0.0 `sie.py` preserves this exact order via the `KEEP_FIELDS` tuple — both for freshly-fetched API issues and for migrated local-export issues. Don't reorder without reason; the order is part of the documented output contract.

`key` is intentionally NOT in `KEEP_FIELDS` — it's added after the filter in local migration (real key from disk if present, else a `local:` synthetic key). For fresh API fetches, `key` is added by the renderer directly from the API response.

## CLI flags (all have shortforms)

Every longform flag has a shortform counterpart:
- `-h` / `--help`
- `-s` / `--summary`
- `-m` / `--migrate`
- `-d` / `--debug-env` (token env var diagnostic — distinguishes not-set / empty / set-with-N-chars)
- `-c` / `--clean` (silently drop Why/How sections — avoid pushing licensed Sonar content)
- `-v` / `--version`

This is a deliberate design rule — don't add a longform flag without a shortform.

## Clean mode (`-c` / `--clean`)

When `--clean` is passed, `sie` silently drops the Why/How rule-rationale subsections from the rendered Markdown — no placeholder, no warning. The `api/rules/show` fetch is skipped entirely (no point fetching content that will be dropped). The header shows `Token: clean (why/how sections suppressed)` instead of present/absent.

**Why**: SonarCloud rule descriptions (the "why"/"how" content) are intellectual property of SonarSource SA. The README's AI disclosure notes: "Rule descriptions and educational content are the intellectual property of SonarSource SA. This tool does not bundle or redistribute SonarSource content." When sharing a `sie` export with a chat agent (or pushing to a public repo), use `-c` to ensure no licensed content leaks.

**What's preserved**: the Instances table (file, line, message, severity, rule key) is the user's own project's scan results — not licensed content. The Summary table (severity/type counts, top rules) is also safe. Only the rule rationale sections are suppressed.

## Deployment pipeline (replaces sie-migrate.sh)

The `ai/chat.z.ai/scripts/` directory contains a deploy pipeline (see `scripts/README.md` for the per-script reference and the agent-facing delivery workflow):

- `upload.sh` (renamed → `repomix.sh`) — repomix the repo and copy zip path to clipboard (for uploading context to a chat session). A new `zip.sh` was added for pure-zip uploads of arbitrary files (debug logs, transcripts, screenshots) — both source `.base.sh` and define a `snippet()` function with the workflow-specific command (mirrors LineByLine's `.base.sh` pattern).
- `delivery/prepare.sh` — sandbox-side: zip deliverables + `deploy.sh` into `deliver.zip`
- `delivery/deploy.sh` — user-side: deploy files, install `sie.py`, clean 0.2.x artifacts, run `uv sync --extra dev` + `ruff check --fix sie.py` (autofix) + `ruff check sie.py` (gate, includes C901 mccabe complexity) + `pytest tests/ -v`. **Supersedes `sie-migrate.sh`** — the migration logic is folded in.
- `delivery/unpack.sh` — user-side entry point, run via the `dsie` fish abbreviation

The `dsie` fish abbreviation: `abbr --add dsie '~/GitHub/sonar-issue-exporter/ai/chat.z.ai/scripts/delivery/unpack.sh'`

`sie-migrate.sh` is now legacy — delete it after adopting the `dsie` pipeline. The `deploy.sh` script does everything `sie-migrate.sh` did (uninstall old uv tool, remove old symlinks, clean 0.2.x artifacts, install `sie.py`) PLUS deploys session files, runs the Ruff autofix + gate, and runs the test suite.

**Ruff gate**: deploy.sh aborts if `ruff check sie.py` fails after `ruff check --fix` (which only applies safe fixes). The agent should pre-lint in-sandbox (`uv run ruff check --fix sie.py` then `uv run ruff check sie.py`) before delivering — a failed gate on the user's machine means a back-and-forth to fix lint issues that the agent could have caught in-sandbox.

**Collision-cleanup bug (fixed v1.0.0, regressed + re-fixed v1.0.0)**: the cleanup phase at the end of `deploy.sh` now removes ONLY the files that came from `deliver.zip`, per a `.deliver-files.list` manifest that `unpack.sh` writes before extraction. Pre-existing files in `scratch/` (scratch.md notes, prior session zips, anything the user stashed there) are preserved.

Bug history: the first version of the cleanup used `find . -maxdepth 1 -type f` after `cd "$DEST"` for uv sync, which walked the **repo root** and deleted `.gitattributes`, `.gitignore`, `LICENSE`, `sie.py`, `README.md`, `pyproject.toml`, `uv.lock` (postmortem: `archive/1.0.0/bug.md`). The second version added `cd "$SCRATCH"` to fix that, but `find . -maxdepth 1` still swept every file in `scratch/`, deleting a user's `scratch.md` notes (postmortem: same `archive/1.0.0/bug.md`). The manifest-based scoping is the root fix: only files the agent put in `scratch/` (per the zip) get cleaned up, period. If you ever modify the cleanup phase, preserve the manifest-based scoping — don't go back to `find .`.

## `uv sync` for dev deps

Dev dependencies (pytest, ruff) are in `pyproject.toml`'s `[project.optional-dependencies] dev = [...]`. Install with `uv sync --extra dev` (not `pip install -e ".[dev]"`). `uv sync` is idempotent: if `.venv/` exists and `pyproject.toml` hasn't changed, it's a no-op. If deps changed (new test file, new helper) or `.venv/` was deleted, it recreates the venv with the exact deps. `uv run pytest tests/ -v` invokes pytest using the venv's Python — no manual activation needed.

## 0.2.x → 1.0.0 migration contract

The `sie-migrate.sh` script is nondestructive and idempotent. It:
1. `uv tool uninstall sonar-issue-exporter` (if installed)
2. Removes `~/.local/bin/sonar-export` and `~/.local/bin/sonar-watch` (file or symlink)
3. Copies `sie.py` → `~/.local/bin/sie`, `chmod +x`
4. Verifies `sie --version`

The same contract is followed by `delivery/deploy.sh` (which additionally deploys session files, runs the Ruff gate, and runs pytest). `sie-migrate.sh` is legacy; `deploy.sh` is the canonical migration path going forward.

The user's `~/.env` file (if they had one for 0.2.x) is left untouched — but `sie` 1.0.0+ no longer reads it. The user must migrate their API key to the shell environment (`set -gx SONAR_API_KEY ...` in fish, or `export SONAR_API_KEY=...` in bash/zsh). Re-running the script on an already-migrated machine is safe.

## What training shadows (flag for the agent)

- **SonarCloud vs SonarQube**: training data often conflates these. SonarCloud is the SaaS; SonarQube is the self-hosted. The API is nearly identical, but `sie` is hardcoded to `https://sonarcloud.io` and won't work against a self-hosted SonarQube instance without code changes. Don't suggest `sie` for SonarQube (self-hosted) workflows.
- **`uv tool install`**: training data may suggest this as the install path for any Python tool. For `sie` 1.0.0+, the install is a single `install -Dm755 sie.py ~/.local/bin/sie` — no build step, no venv, no symlink into a Python package directory. The `uv tool` route is only relevant for the legacy 0.2.x install (and the migration script handles uninstalling it).
- **`pyperclip`**: training data may suggest this for clipboard handling. `sie` 1.0.0 dropped clipboard watching entirely — the API can enumerate issues without manual URL collection, so the watcher is gone. Don't suggest adding `pyperclip` back.
- **`html2text`**: training data may suggest this for HTML→Markdown conversion of rule descriptions. `sie` 1.0.0 uses a crude stdlib-only HTML stripper instead — adequate for SonarCloud's simple HTML (p, code, a, strong, br). Don't suggest `html2text` unless the user reports actual rendering issues with a specific rule's description.
- **`.env` files**: training data may suggest `.env` for config. `sie` 1.0.0+ reads the API key exclusively from environment variables (no `.env` file reading). The user's setup uses KDE Wallet + fish shell `set -gx` — don't suggest `.env` as an alternative.

## Cognitive-complexity reduction pass (v1.0.0)

`render_markdown`, `parse_local_export`, and `discover_repo` were refactored to bring their mccabe complexity (C901, default threshold 10) under threshold. The pattern: extract one helper per section/discovery-source, keep the top-level function as a composition root. `render_markdown` dropped from CC 30 to ~3 by extracting 10 helpers (`_scope_display`, `_render_header`, `_render_focal_issue`, `_compute_facets`, `_render_summary_section`, `_render_why_section`, `_render_how_section`, `_render_instances_table`, `_render_per_rule_section`, `_render_per_rule_sections`). `parse_local_export` dropped by extracting `_parse_issue_from_json` + `_register_rule_metadata`. `discover_repo` dropped by extracting `_discover_from_package_json` + `_discover_from_pyproject` + `_discover_from_git_remote`. C901 was re-enabled in `pyproject.toml`'s `[tool.ruff.lint] select` after the refactor passed. C901 (mccabe) and SonarCloud's S3776 (cognitive, threshold 15) measure different things — both are intentionally enabled; a function that exceeds EITHER metric warrants a refactor. See `code-quality-SKILL.md` for the reduction techniques.

## Versioning

Patch releases for `sie` (e.g. 1.0.0 → 1.0.1) are for bug fixes and small enhancements. Minor version bumps (1.0.x → 1.1.0) are for new features that change the CLI surface or output format. Major version bumps (1.x.y → 2.0.0) are reserved for breaking changes that require a fresh migration. The version is hardcoded at the top of `sie.py` as `VERSION = "1.0.0"` — update it in lockstep with the `pyproject.toml` `version` field and the `README.md` references.