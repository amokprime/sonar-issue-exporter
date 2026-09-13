---
name: code-quality
description: Proactively avoid code quality issues and silent regressions in the sonar-issue-exporter Python script (sie.py) and the sie-migrate.sh shell script. Use this skill whenever writing or modifying Python in sie.py, especially when adding new input forms, changing URL parsing, modifying the Markdown renderer, or extending the test suite. Also use when writing or modifying sie-migrate.sh. Also use when the user mentions SonarQube, cognitive complexity, S3776, S5713, code smells, ruff, or when reviewing code for potential regressions. This skill prevents issues before they reach SonarCloud scans.
---

Documents the code quality patterns that SonarCloud has flagged in this project and the silent regressions that occurred during development. Following these rules proactively prevents issues rather than fixing them after SonarCloud flags them.

---

Cognitive Complexity (S3776) — threshold 15

The maximum allowed cognitive complexity per function is 15. SonarCloud evaluates each function independently.

Primary reduction techniques, in order of preference:

1. Extract helper functions — method calls are free in CC calculation.
2. Early returns — process exceptional cases first and return, reducing nesting depth.
3. Extract complex conditions — `if is_supported_url(raw):` instead of `if raw.startswith("http://") or raw.startswith("https://"):` — inline `or` chains add +1 per operator change.
4. Dispatch tables — when a function is a long chain of `if` branches keyed on the same value, convert to a dict lookup. `sie.py`'s `resolve_input` uses this pattern implicitly (URL vs fuzzy vs path), though it's structured as early-returns rather than a table because each branch needs different pre-processing.

CC accounting in SonarCloud:
- `if`, `else if`, `else`: +1 each
- `for`, `while`: +1 each
- `&&`, `||`: +1 for each change of operator in a condition
- `? :` ternary: +1
- Nesting adds +1 per level for `if`/`for`/`while`/`catch`
- Method calls: 0 (free) — this is why extraction works

When `sie.py`'s `main()` or any helper grows past ~15 cognitive complexity (S3776) or ~10 mccabe complexity (C901), extract a helper rather than letting it bloat. The test suite (`tests/test_cli.py`, `tests/test_markdown_render.py`) will catch behavior regressions on the extracted helper.

The v1.0.0 refactor extracted these helpers from `render_markdown` (was CC 30 / mccabe 30) to bring it under both thresholds: `_scope_display`, `_render_header`, `_render_focal_issue`, `_compute_facets`, `_render_summary_section`, `_render_why_section`, `_render_how_section`, `_render_instances_table`, `_render_per_rule_section`, `_render_per_rule_sections`. Each helper renders one section of the report; `render_markdown` itself is now a ~10-line composition root. The same pattern was applied to `parse_local_export` (`_parse_issue_from_json`, `_register_rule_metadata`) and `discover_repo` (`_discover_from_package_json`, `_discover_from_pyproject`, `_discover_from_git_remote`). Follow this pattern when future growth pushes another function over threshold — extract, don't bloat.

The v1.1.0 CodeQL auto-discovery feature followed the same pattern: `export_url` would have grown past CC 15 with the new CodeQL fetch + three-way render dispatch, so two helpers were extracted: `_fetch_code_scanning_for_project` (silent-drop repo-wide alert fetch + SonarCloud-push dedup) and `_render_export_markdown` (three-way dispatch: both / sonar-only / codeql-only / empty). The combined renderer `render_combined_markdown` itself is split into `_render_combined_header` (project-level header with per-source counts) and `_render_combined_source_section` (one `## <Source>` heading + demoted body), each well under threshold.

---

Redundant exception class (S5713)

`except (OSError, PermissionError)` is redundant — `PermissionError` is a subclass of `OSError`. Drop the subclass:

```python
# Wrong:
except (OSError, PermissionError):
    ...

# Right:
except OSError:
    ...
```

The 0.2.x `export_sonar_issue.py` had this exact finding at line 96 (per `archive/0.2.0/issues/`); the 1.0.0 `sie.py` was written to avoid it from the start. Don't reintroduce.

---

Mutable default arguments (S5712)

Python evaluates default arguments once at function definition time, not at call time. Mutable defaults (`[]`, `{}`, `set()`) shared across calls cause spooky-action-at-a-distance bugs.

```python
# Wrong:
def add_issue(issue, rules={}):
    rules[issue["rule"]] = issue
    return rules

# Right:
def add_issue(issue, rules=None):
    if rules is None:
        rules = {}
    rules[issue["rule"]] = issue
    return rules
```

`sie.py` uses module-level constants (`SEVERITY_ORDER`, `KEEP_FIELDS`, `DEFAULT_INCLUDES`) instead of mutable defaults — these are read-only by convention and never mutated.

---

Field ordering (KEEP_FIELDS)

The `KEEP_FIELDS` tuple controls the displayed field order for issue JSON in the Markdown output: `rule, component, line, textRange, message, severity, type, cleanCodeAttribute, cleanCodeAttributeCategory, impacts, flows`. This order is part of the documented output contract (per `archive/0.1.2/0.1.2.md` — "identity → location → description → classification → evidence").

Don't reorder without reason. The order makes the per-issue JSON scannable: 9 one-liner values come first, then the multi-line arrays (`impacts`, `flows`) at the end where they don't push quick-scan info off screen.

`key` is intentionally NOT in `KEEP_FIELDS` — it's added after the filter in local migration (real key from disk if present, else a `local:` synthetic key). For fresh API fetches, `key` is added by the renderer directly from the API response. This is documented in `MEMORY.md`.

---

HTML stripping for rule descriptions

`sie.py` uses a crude stdlib-only HTML stripper (`_strip_html`) instead of `html2text`. SonarCloud rule descriptions are simple HTML (p, code, a, strong, br) — the stripper handles these adequately. The 0.2.x code had `html2text` as an optional dependency; the 1.0.0 refactor dropped it to keep the script zero-dep.

If a specific rule's description renders incorrectly, the fix is to extend `_strip_html` (e.g. handle a new tag), not to add `html2text` back. Don't reach for a third-party dep when a stdlib extension works.

---

URL parsing — preserve extra params

`sie.parse_url_input` must preserve all query params from SonarCloud UI URLs through to the API URL — `sinceLeakPeriod`, `rules`, `tags`, etc. The 1.0.0 refactor had a bug where the initial implementation dropped these; the test `test_ui_url_preserves_extra_params` (in `tests/test_url_parsing.py`) catches this regression. When modifying `parse_url_input`, run that test specifically: `pytest tests/test_url_parsing.py -k "extra_params" -v`.

The mapping is: UI `?id=<PROJECT>` becomes API `?componentKeys=<PROJECT>` (renamed); UI `?open=<KEY>` becomes the `focal_key` descriptor field (consumed, not passed through); everything else passes through verbatim.

---

GitHub URL — branch names with slashes

GitHub branch names can contain slashes (e.g. `feature/sync-rewrite`). The `/tree/<branch>` URL form preserves the full branch name across the slash; the `/blob/<branch>/<path>` form has only one segment after `/blob/` as the branch (the rest is the file path). `sie.parse_github_url` handles these differently — `tree` joins everything after `/tree/`, `blob` takes only the first segment. The test `test_branch_with_slashes_in_name` covers this. When modifying GitHub URL handling, run: `pytest tests/test_github_url.py -v`.

---

Local-path disambiguation

`sie.main()` treats a single path-like positional as the OUTPUT path (with input defaulting to main of CWD's repo), NOT as a migration input. Local-folder migration requires `--migrate`. This was the v1.0.0 disambiguation refactor — see `MEMORY.md` for the rationale.

`resolve_input()` explicitly raises `ValueError` on path-like inputs — this is intentional. The CLI layer catches path-like positionals BEFORE calling `resolve_input`. If you find yourself adding a path-like branch to `resolve_input`, stop — that's the bug the refactor removed. Use the CLI layer instead.

---

Bash script patterns (delivery/deploy.sh, prepare.sh, unpack.sh, repomix.sh, zip.sh, .base.sh)

The scripts in `ai/chat.z.ai/scripts/` are bash, and `sie-migrate.sh` (legacy) is a short POSIX shell script. The same patterns apply to all of them:

- **Strict mode**: `set -euo pipefail` (the `-o pipefail` catches mid-pipe failures; the upload scripts don't pipe, but the delivery scripts do — `unzip -l | awk`, `find ... | while read`). Any failing command aborts before the destructive install step.
- **Empty-variable guards**: every `rm` with a variable path uses `${var:?}` (ShellCheck SC2115). `deploy.sh`'s `rm_if_exists` and the cleanup loop both follow this; `unpack.sh`'s `cleanup()` trap too.
- **Braceless compounds**: avoid `[ cond ] && exit` — use `if [ cond ]; then ...; fi` with an explicit `exit 1` and stderr message.
- **Diagnostics and exit codes**: error messages go to stderr (`echo "..." >&2`), and every `exit` carries an explicit status.
- **Config over constants**: paths derive from `$HOME` + `SONAR_ISSUE_EXPORTER_ROOT` (or `LINEBYLINE_ROOT` in the LineByLine originals) + `XDG_BIN_HOME` (with `~/.local/bin` fallback), not hardcoded `/home/user/...`.
- **Base/source pattern**: the upload scripts (`repomix.sh`, `zip.sh`) define a `snippet()` function and source `.base.sh`, which handles the shared setup (path resolution, scratch/upload dir, zip + clipboard). Mirrors LineByLine's `.base.sh` pattern. When adding a new upload workflow, define a new `snippet()` and source `.base.sh` — don't duplicate the setup logic. The delivery scripts (`prepare.sh`, `deploy.sh`, `unpack.sh`) don't source `.base.sh` — they have their own shared variables.
- **Cleanup scoping**: `deploy.sh`'s collision-cleanup reads a `.deliver-files.list` manifest (written by `unpack.sh` before extraction) and removes only those files. Never use `find . -maxdepth 1 -type f` for the cleanup — it sweeps pre-existing files in `scratch/` (scratch.md notes, prior session zips). See `archive/1.0.0/bug.md` for the post-mortem on the two prior `find .` regressions.

Run `bash -n` on each script after any change to catch syntax errors. ShellCheck if available: `shellcheck ai/chat.z.ai/scripts/delivery/deploy.sh`. (Note: `bash -n` is required, not `sh -n` — these scripts use bash arrays and `mapfile`, which dash doesn't support.)

---

Pre-delivery code quality checklist

Before delivering any patch to `sie.py`, verify:

1. **CC of modified functions** — estimate the cognitive complexity of any function you changed. If it exceeds 15, extract helpers or use early returns before delivering.
2. **Redundant exception class** — check every `except` tuple in the patch for parent/child redundancy.
3. **Mutable default args** — check every function signature in the patch for `={}` or `=[]` defaults.
4. **Field ordering** — if the patch touches `KEEP_FIELDS` or the renderer, verify the output contract is preserved. Run `pytest tests/test_markdown_render.py`.
5. **URL parsing** — if the patch touches `parse_url_input` or `parse_github_url`, run the full `tests/test_url_parsing.py` and `tests/test_github_url.py` suites. The extra-params and branch-slash cases are the most regression-prone.
6. **CLI disambiguation** — if the patch touches `main()`, run `tests/test_cli.py`. The disambiguation logic is subtle — the tests are the spec.
7. **Local migration** — if the patch touches `parse_local_export`, run `tests/test_local_migration.py`. The `local:` prefix and `Lunknown` handling have specific tests.
8. **Lint** — `uv run ruff check --fix sie.py` (autofix safe violations) followed by `uv run ruff check sie.py` (gate — zero findings required). The rule set is configured in `pyproject.toml` `[tool.ruff.lint] select = ["E","W","F","I","C90","UP","B"]` — pycodestyle, pyflakes, isort, mccabe complexity (C901, default threshold 10), pyupgrade, flake8-bugbear. C901 (mccabe) and SonarCloud's S3776 (cognitive, threshold 15) measure different things — both are intentionally enabled; a function that exceeds EITHER metric warrants a refactor. The deploy pipeline (`dsie`) runs the same two ruff commands as a gate, so pre-linting in-sandbox avoids the gate failing on the user's machine.

For `delivery/deploy.sh` (and the other delivery scripts):
1. `bash -n ai/chat.z.ai/scripts/delivery/deploy.sh` (syntax check — must be `bash -n`, not `sh -n`, because the scripts use bash arrays + `mapfile`)
2. `shellcheck ai/chat.z.ai/scripts/delivery/deploy.sh` if available
3. The deploy pipeline is idempotent — re-running `dsie` on an already-deployed state should be a no-op (the `cmp -s` byte-identical check skips unchanged files, the cleanup is `rm_if_exists`-guarded, and `uv sync` is a no-op when `pyproject.toml` hasn't changed).
