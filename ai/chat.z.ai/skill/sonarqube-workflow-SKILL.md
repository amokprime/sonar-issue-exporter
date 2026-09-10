---
name: sonarqube-workflow
description: Process SonarCloud issues for the sonar-issue-exporter project and guide remediation. Use this skill whenever the user asks about SonarQube findings, mentions rules like S3776/S2004/S2681/S5713, needs help deciding whether to fix or mark as Won't Fix, or wants to plan a SonarQube remediation pass before writing any code. Also use when the user uploads a Markdown file produced by `sie`, or when the agent should enumerate issues directly from the SonarCloud public API (no user upload needed for issue enumeration).
---

SonarCloud scans run on every push via GitHub Actions. The sandbox can enumerate issues directly via the public JSON API (no auth, no `sie`); for rule rationale (`why`/`how` content), the user runs `sie '<URL>'` locally with `SONAR_API_KEY` set and uploads the resulting Markdown. The two paths complement each other: API for "what's firing where right now", local `sie` export for "why this rule and how to fix it".

---

Step 0: Sandbox API enumeration (preferred first step)

Before asking the user to run `sie` locally, fetch the current issue list directly from the SonarCloud public JSON API. The project is public (`amokprime_sonar-issue-exporter`), so issue enumeration works unauthenticated.

Endpoints (use Python `urllib`, not the web reader tool — the web reader's URL validator rejects some query strings and the SPA pages render nothing for a static reader):

- Main-branch OPEN issues:
  ```
  https://sonarcloud.io/api/issues/search?componentKeys=amokprime_sonar-issue-exporter&issueStatuses=OPEN
  ```
- PR-scoped OPEN issues (replace `N` with the open PR number):
  ```
  https://sonarcloud.io/api/issues/search?componentKeys=amokprime_sonar-issue-exporter&pullRequest=N&issueStatuses=OPEN
  ```

Optional query params:

- `&facets=rules,severities,types` — first-pass triage: returns summary counts without fetching every issue. This is what `sie --summary` does internally.
- `&rules=python:S5713` — narrow to one rule.
- `&ps=500` — page size (default 50, max 500). `sie` forces this to 500.
- `&p=2` — page number, if `total > ps`.
- `&issueStatuses=OPEN,CONFIRMED` — comma-separated multi-status works in raw form via Python urllib.

What the API returns: each issue has `key`, `rule`, `severity`, `component`, `line`, `message`, `status`, `type`, `cleanCodeAttribute`, `cleanCodeAttributeCategory`, `impacts`, `creationDate`, `updateDate`. The `key` is the stable identifier; the `component` is the file path (e.g. `amokprime_sonar-issue-exporter:sie.py`); the `rule` is the rule key (e.g. `python:S5713`).

Auth boundary (verified Sep 2026): issue enumeration, facets, and rule filtering work unauthenticated. The following endpoints require auth + the `organization` query param, and return HTTP 400 without it:

- `api/rules/show?key=<rule>&organization=<org>` — rule "why"/"how" content. For rule rationale, the user runs `sie '<URL>'` locally with `SONAR_API_KEY` set and uploads the resulting Markdown (see Step 1).
- Single-issue lookup via `?issues=<KEY>` on `api/issues/search` — returns 0 results without auth. To check a specific issue's status, filter by `rules=<rule>` + `component=<component>` instead, or fetch all OPEN issues and grep the response for the key.

Closed-issue gotcha: closed issues have `line: null` in the API response. In `sie`'s Markdown output, these render with `Lunknown` in the Line column. When triaging an export the user uploaded, cross-check each issue's `key` against the live API to detect staleness — a closed/FIXED issue in a fresh export is stale, not new. The API's `status` field is the source of truth: `OPEN`, `RESOLVED`, `CLOSED`.

When to skip Step 0 and go straight to Step 1: only when the user has already uploaded a `sie`-produced Markdown file AND wants the why/how rule rationale that the API cannot provide. In that case, the export is the authoritative source — but still run Step 0 in parallel to cross-check issue statuses (catches the closed-issue staleness gotcha).

---

Step 1: Read a `sie`-produced Markdown export (when the user uploads one)

Layout (v1.0.0+ single-file Markdown, replacing the 0.2.x per-issue folder tree):

```markdown
# SonarQube Issues — <project> (<scope>)

Generated: <timestamp>
Source: `<input URL or local path>`
Total: N issue(s) across M rule(s)
Token: present | absent

> ⚠ **No token set** — why/how rule-rationale subsections render as placeholders.
  (Only appears when no token was available.)

---

## ★ Focal Issue                    # only when ?open=<KEY> was in the URL
- **Key:** `<KEY>`
- **Rule:** `<rule>`
- **File:** `<component>:<line>`
- **Severity:** ... · **Type:** ... · **Status:** ...
- **Message:** ...
→ [Open in SonarCloud](<deep link>)
→ See rule section: [`<rule>`](#<anchor>)

---

## Summary
| Severity | Count |   | Type | Count |
| ... |
Top rules:
- `<rule>` — N×

---

## Rule: `<rule>` — <name>
Severity: ... · Type: ... · CleanCode: ... · N instance(s)

### Why
<rule rationale — fetched via api/rules/show when token present, else placeholder>

### How to fix
<fix guidance — fetched via api/rules/show when token present, else placeholder>

### Instances
| File | Line | Message | Key | Status |
| ... | Lunknown | ... | `local:...` | OPEN |  # Lunknown = closed-issue marker

Deep links: `https://sonarcloud.io/project/issues?open=<KEY>&id=<PROJECT>`
```

Read the `### Why` and `### How to fix` sections once per rule. Scan the `### Instances` table for every finding — each row is a separate issue. Issues with `Lunknown` in the Line column are closed issues (the `line: null` gotcha from Step 0) — verify their `status` before triaging.

For 0.2.x local-folder exports (the legacy per-issue folder layout: `<category>/L{line}.json` + `why.md` + `how.md`), use `sie --migrate <folder>` to convert to the single-file Markdown format first.

---

Step 2: Categorize by rule

Group findings before acting. Common rules in this project (the sonar-issue-exporter codebase is small, so the rule set is narrow):

| Rule | Name | Typical fix | False positive risk |
|---|---|---|---|
| `python:S3776` | Cognitive Complexity | Helper extraction, early return | Low — `sie.py`'s `main()` is the most likely candidate if it grows |
| `python:S5713` | Redundant exception class | Drop the redundant subclass (`except (OSError, PermissionError)` → `except OSError`) | Low — `PermissionError` is a subclass of `OSError` |
| `python:S5712` | Mutable default args | Use `None` sentinel + `if x is None: x = []` | Low |
| `python:S1488` | Right-size generator | Move generator expression inside `list()` / `sum()` | Low |
| `python:S905` | Non-empty slice with `step` | Verify step direction matches start/stop | Medium — easy to get backwards |
| `text:S8565` | Lock file missing | Add `uv.lock` (project uses `uv`) | Low |

Shell rules (if `sie-migrate.sh` grows beyond its current size):

| Rule | Name | Typical fix |
|---|---|---|
| `shelldre:S7682` | Explicit return | Add `return 0` / `return N` to shell functions |
| `shelldre:S7679` | Positional params → locals | `local foo="$1"` at function top |
| `shelldre:S7688` | `[` → `[[` | Use bash `[[` for conditionals |

---

Step 3: Assess each finding individually

Never apply a rule category wholesale. Assess each instance:

- **S3776 (Cognitive Complexity)** — `sie.py` is the main file. Functions like `main()`, `export_url()`, and `render_markdown()` are the natural complexity sinks. The 0.2.x `export_sonar_issue.py`'s `main()` was at CC 27 (per `archive/0.1.2/`); the 1.0.0 `sie.py` was deliberately refactored to keep complexity down via `_build_descriptor`, `resolve_input`, etc. When adding a new input form, prefer extracting a helper over inline branching.
- **S5713 (redundant exception class)** — only triggers when a subclass is listed alongside its parent in an `except` tuple. Drop the subclass; the parent catches it.
- **S905 (slice with step)** — verify the step direction matches the start/stop semantics. Easy to get backwards when refactoring a slice.

---

Step 4: Plan the remediation pass

Group accepted fixes by file. Since `sie.py` is the only non-trivial source file, most fixes land there. The test suite (`tests/`) catches regressions on the parsing/resolution/rendering logic — run `pytest tests/` after any non-trivial change.

Typical order:
1. Simple substitutions first (exception class dedup, slice direction, lock file).
2. Cognitive complexity reduction (S3776) — most invasive, do last.
3. Shell-script rules (if `sie-migrate.sh` grows) — independent of Python code.

---

Step 5: Won't Fix rationale

Document Won't Fix decisions in the chat output for the user to record. Standard rationales:

- **S3776 deferred**: "Deferred: function complexity is at the edge; structural refactor would expand scope beyond this patch. Tracked for next minor version."
- **S905 false positive**: "Won't Fix: slice direction is correct as written; the rule's heuristic misfires on this specific pattern."
- **S5713 deferred**: rare — these are usually trivial to fix.

In the SonarCloud UI, the resolution options are "False Positive" and "Accept" (no "Won't Fix" label). Use "False Positive" for analyzer-error cases, "Accept" for intentional-design cases.

---

Step 6: Version and delivery

SonarQube remediation passes are patch releases (e.g. 1.0.0 → 1.0.1). Update the `VERSION` constant at the top of `sie.py` in lockstep with the `pyproject.toml` `version` field and the `README.md` references.

After delivery, SonarCloud will re-scan on the next push. To force a re-scan without a push, the user can re-run the SonarCloud workflow via `workflow_dispatch` (enabled on `sonarcloud.yml`).