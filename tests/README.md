# tests — sonar-issue-exporter test suite

Pytest-based tests for `sie.py`. Covers the parts of `sie` that have
non-trivial logic and are likely to regress:

- `test_url_parsing.py` — SonarCloud API/UI URL parsing, including
  extra-param passthrough (`sinceLeakPeriod`, `issueStatuses=OPEN,CONFIRMED`)
  and the `?open=<KEY>` focal-issue extraction.
- `test_input_resolver.py` — top-level `resolve_input` dispatch:
  SonarCloud URL, GitHub URL, fuzzy `owner/repo[/branch]`, single-token
  shortcuts (`pr`, `main`, `<branch>`), no-arg, and the local-path
  sentinel.
- `test_github_url.py` — GitHub URL → SonarCloud descriptor mapping:
  `/owner/repo`, `/pull/N`, `/tree/<branch>`, `/blob/<branch>/...`,
  `/commit/<sha>` (error case), SSH form, `git+https://` form.
- `test_local_migration.py` — `parse_local_export` walking the 0.2.x
  folder layout: `L{line}.json`, `Lunknown.json` (closed-issue marker),
  shared `why.md`/`how.md` per category, missing `key` field handling.
- `test_cli.py` — `main()` positional disambiguation: `sie` (bare),
  `sie <path>` (output-only), `sie <input> <path>`, `sie --migrate <path>`,
  ambiguous case, missing path errors.
- `test_markdown_render.py` — `render_markdown` shape: Focal Issue
  callout, summary table, per-rule sections, `local:` prefix on
  synthetic keys.

## Running

```sh
# Install dev deps (pytest only — sie.py itself is zero-dep):
pip install pytest

# Run all tests from the repo root:
pytest tests/ -v

# Run a single test file:
pytest tests/test_url_parsing.py -v

# Run by keyword:
pytest tests/ -k "focal" -v
```

## Design notes

- **No network**: tests that would hit SonarCloud (or `gh`) are skipped
  unless the relevant env var is set (`SIE_NETWORK_TESTS=1` for live API
  calls, `GH_TOKEN` for `gh pr list`). The default suite is fully
  offline — pure unit tests on the parsing/resolution/rendering logic.
  This keeps CI fast and lets the tests run inside a chat.z.ai sandbox.

- **No `sie.py` import path hacks**: tests use `sys.path.insert(0, "..")`
  at the top of each file. This avoids needing to install `sie.py` as
  a package — `pytest tests/` from the repo root just works.

- **Fixtures in `conftest.py`**: shared fixtures for the local-export
  folder layout (built from the actual `archive/0.1.2/issues/` shape
  documented in `sonarqube-workflow-SKILL.md`) live in `conftest.py`.

- **What's NOT tested**: the actual `urllib.request.urlopen` call in
  `_api_get` — we mock at the `fetch_issues` / `fetch_rule` level using
  monkeypatch. This keeps tests fast and deterministic.

## Adding tests

When adding a new input form or output behavior to `sie.py`, add a
corresponding test in the matching file. The test should:

1. Construct the minimal input that triggers the new code path.
2. Assert on the descriptor dict (for input resolver tests) or on the
   rendered Markdown (for renderer tests) — not on stdout/stderr.
3. Include a one-line comment naming the `sie.py` function under test
   so future readers can grep for the coverage.

Tests that require network access go in `test_network.py` (not yet
present — add when the first one is needed) and are skipped by default
via the `skipif` marker.
