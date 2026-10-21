---
name: sonar-issue-exporter
description: Project onboarding, session workflow, and patch delivery for the sonar-issue-exporter Python CLI (`sie`). Use this skill at the start of every session (after `setup-sandbox.sh`), whenever you need to locate project files, follow the build/patch workflow, version the script, or decide whether `MEMORY.md` or another skill needs updating after a change. Also use when the user mentions a vibecoding step (Onboard, Code, Skills, Propose) or asks about project structure. This skill is the single onboarding + workflow reference — read it once at session start, re-read at step boundaries if context compacts.
---
This is the canonical project onboarding + workflow skill. Project structure lives in `AGENTS.md` (read once at Onboard, not every turn). Web-channel behavioral rules + the delivery workflow live in the `delivery` skill — invoke `Skill(command="delivery")` when the task touches file visibility, output format, comment density, or the prepare → zip → deploy pipeline. Specialized domain knowledge lives in the domain skills (`code-quality`, `sonarqube-workflow`) — invoke those via `Skill(command="name")` when their description matches the current task.

This skill covers: (1) context loading, (2) the vibecoding workflow steps, (3) pre/post-patch checklists, (4) post-turn documentation hygiene, and (5) versioning. The chat.z.ai web channel is the only interaction surface — but the channel-specific behavioral rules and the delivery scripts live in the `delivery` skill, not here.

---
Context loading

The chat.z.ai web channel does not auto-inject context files — the agent must Read them explicitly. To streamline this, `skills/delivery/scripts/setup-sandbox.sh` copies the project skills into `/home/z/my-project/skills/` so their `description` frontmatter auto-loads into the sandbox's `available_skills` list (invokable via `Skill(command="name")`). Run it once at Onboard after cloning the repo; it's idempotent. Root-level `AGENTS.md` and `MEMORY.md` do NOT auto-load — they must be Read explicitly (the Espanso snippets in `scripts/espanso.yml` insert the clone + read instructions).

The Espanso snippets define which files to read per step. See `ai/README.md` for the current trigger list (`:scm`, `:sco`, `:ssk`).

Context loading strategy

The repo tree is small (`sie.py` is ~2800 lines, `tests/` is ~50 files, `docs/` is 6 files, `archive/` is per-version). Targeted reads still beat bulk reads:

- Use Glob to list files matching a pattern (e.g. `tests/test_*.py`) instead of LS on the repo root.
- Use Grep to find functions in `sie.py` (`def parse_url_input`, `def render_markdown`, `def main`) and read just those ranges instead of the whole file. `sie.py` is the only file large enough to warrant this — for everything else, just Read it.
- For `tests/`, read only the files relevant to the current task. The Espanso `:sco` snippet says "read only the files relevant to the current task" — don't interpret "tests/" as "read all of tests/".

When the task spans multiple files (e.g. a patch touching `sie.py` + `tests/test_markdown_render.py` + a doc), use subagents (Task tool, `Explore` type) to read files in parallel. Launch them in a single message with multiple tool calls. Each subagent reads its assigned files and returns a summary.

Caveat: subagents do NOT have access to the full conversation context or skill instructions. Only delegate file-reading/exploration tasks — not tasks requiring skill compliance, content depth standards, or document formatting rules. For those, read the files yourself.

---
Re-read cadence

Re-read this skill (and the `delivery` skill) at the start of each new step and whenever the user announces a step change. The agent's context compacts over long sessions — early-turn workflow rules become less reliable later. Re-reading this skill at step boundaries is the countermeasure. The web-channel rules in the `delivery` skill are equally vulnerable to compaction.

---
Workflows and steps

The agent handles the blue square nodes (Build, Review, Test, Skills, Investigate, Plan, Attempt); the user handles the green/red/yellow nodes (Onboard, decisions, push, wrap up). After building or patching, the agent loops Review ↔ Test until both code-quality checks and tests pass — the user does not need to announce "Review step" or "Test step" separately.

The user may pick and choose steps in any order, stitch multiple workflows together, or follow a custom workflow. The user tells you which step they're on; each step can span multiple turns. The user may end a session at any point without a formal wrap-up. The agent's defense against this unpredictability is to keep documentation artifacts (`MEMORY.md`, skills) current after every turn, so that a push at any moment captures a complete audit trail. See Post-turn updates.

Onboard

Trigger: `:scm`. Read `AGENTS.md`, `MEMORY.md`, `pyproject.toml`, `README.md`, `skills/delivery/scripts/{prepare,deploy,setup-sandbox}.sh`, and `scripts/unpack.sh`. Run `bash skills/delivery/scripts/setup-sandbox.sh` to install project skills into the sandbox.

1. Read `AGENTS.md` (minimal pointer to this skill + project structure) and `MEMORY.md` for development history.
2. Read this skill (the `sonar-issue-exporter` skill — you're reading it now) and the `delivery` skill.
3. Note the current `sie` version. The user may state it directly ("Current version: 1.1.0"). If they don't state it, derive it from `sie.py`'s `VERSION` constant at the top of the file, or from `pyproject.toml`'s `version` field, or from the highest semver folder under `archive/`.
4. Do not begin coding — `sie.py` and the domain skills are read on-demand when the Code step begins. Onboard may be the only step in a session (e.g. a pure planning session), or it may be followed by Code or Skills.
5. There is no companion file created at Onboard.

Code (Build + Test + automatic Review)

Trigger: `:sco`. Read `AGENTS.md`, `MEMORY.md`, `sie.py` (use Grep to find functions, read only the ranges you need), `tests/` (only the files matching the patched code), `pyproject.toml`, `docs/` (only the doc matching the area being patched). The domain skills (`code-quality`, `sonarqube-workflow`) auto-load via `setup-sandbox.sh` — invoke them via `Skill(command="name")` when needed.

1. Read `MEMORY.md` for development history if not already read at Onboard.
2. Re-read this skill to refresh the workflow rules.
3. Use Grep to locate functions in `sie.py` (`def parse_url_input`, `def render_markdown`, `def main`, `def export_url`, etc.) and read only those ranges — don't load the entire ~2800-line file unless the task requires it.
4. Follow the user's requests that do not conflict with this skill. Before writing any code, follow the Pre-patch checklist. After every patch, follow Post-patch verification. After every turn (patch or not), follow Post-turn updates.
5. If multiple features are requested, the user may bucket them into a single turn when they're minor or interdependent. If they're independent and substantial, address them sequentially.

Automatic Review loop. After patching, the agent runs Review (audit for issues from the `code-quality` skill) and Test (run `uv run pytest tests/` in-sandbox) until both pass. This loop is agent-driven — the user does not need to announce "Review step" or "Test step" separately. The loop ends when: (a) the agent's code-quality audit finds no issues, AND (b) the pytest suite passes in-sandbox. The user then pushes to `main`; if new SonarCloud issues surface, the user prompts the agent to Review again.

Skills (meta-session)

Trigger: `:ssk`. Read `CONTRIBUTING.md`, `MEMORY.md`, `skills/**` (except this skill + `delivery` + `skill`), `scripts/**`, `ai/**` (except `ai/templates/`), `.omp/AGENTS.md`, `.omp/RULES.md`.

1. Re-read this skill, the `skill` skill, and the `delivery` skill.
2. Work on agent scaffolding — updating skills, pruning `MEMORY.md`, creating new skills, etc.
3. Historical skill-creation transcripts are at `archive/<version>/` — read those if directly relevant to the meta-work being done. Per-version folders hold all session types.

Propose / Investigate / Plan

No dedicated trigger — uses `:scm` context. Used for high-level research and planning that may not produce code.

1. Re-read this skill.
2. Read any relevant skills and project files for the investigation.
3. Proposals may start with half-baked criteria and become more refined in follow-up turns. Investigations may need web searches to rule out alternatives.

---
MEMORY.md discipline

Write one bullet per parallel thread of work, not one bullet per turn. When a session iterates on the same change across multiple turns (fix → regression catch → follow-up), narrating each turn's state as a separate bullet duplicates earlier states — the reader must mentally diff successive bullets to recover the current state. Instead, identify the unique parallel threads in the session and write one bullet per thread, updated in-place to reflect its latest state.

No turn numbers in `MEMORY.md` bullets. Turn numbers are session-local: a version like 1.1.0 can span multiple sessions, and "Turn 7" in one session is unrelated to "Turn 7" in another.

Verbose Memory entries signal skill gaps. When a `MEMORY.md` entry starts explaining how to do something rather than just what happened, that's a sign the knowledge belongs in a skill. `MEMORY.md` should say "Fixed X by doing Y (root cause: Z)." If it needs to say "When doing X, always do Y because Z, and here are the three cases to watch for," that's a skill.

`MEMORY.md` is for the unexpected, not the expected. Don't record "Verification: 182/182 pytest pass" — passing is the statistical norm; recording it adds noise. Record persistent failures, reproducible gotchas, and counterintuitive constraints — the things a fresh agent would get wrong without reading `MEMORY`. If nothing unexpected happened, write nothing.

Don't record transient/intermediate states. If a feature was added then removed in the same session (never committed), it doesn't belong in `MEMORY` — it's not visible to git history. `MEMORY` records the final settled state. When in doubt about whether a change is settled, wait a turn for user feedback (including silence/"no notes" for what worked out of the box) before writing the `MEMORY` entry.

Don't duplicate canonical comparison tables. If a front-facing doc (e.g. README's feature-comparison table) is the canonical source for a comparison, don't restate the comparison in `MEMORY`. `MEMORY` points to the canonical doc, not duplicates it.

Pruning preserves history. Pruning a `MEMORY.md` entry means condensing it to a brief reference, not deleting it. Past session entries are historical records. Only prune entries you created or updated this session; leave past session entries intact unless they are now fully redundant with a skill.

The agent edits `MEMORY.md` in-sandbox and produces the updated file in `download/` for the user to apply to the repo. Apply updates inline — do not propose them as drafts for the user to approve.

---
Pre-patch checklist

Before writing any code change:

1. Stop and request clarification when: a request is unclear or overly complex, relevant files are missing, a request is technically infeasible, or a request violates best practices from a skill.
2. Read only the sections you need — use Grep to find functions in `sie.py` and read just those ranges. This avoids loading the entire ~2800-line file when only a few functions are relevant.
3. Patch with minimal diff — change only what's needed and preserve surrounding code. Prefer targeted edits over full-section rewrites unless the section is being restructured.
4. Consult the `code-quality` skill before modifying functions in `sie.py` (cognitive complexity threshold 15, redundant-exception-class gotcha, mutable defaults, KEEP_FIELDS ordering, URL-parsing param passthrough, GitHub branch-slash handling, CLI disambiguation).

---
Post-patch verification

After every patch, before delivering:

1. Syntax check — `python3 -c "import py_compile; py_compile.compile('sie.py', doraise=True)"` or `uv run python -c "import sie"`. A syntax error in `sie.py` means the entire script is broken.
2. Lint — `uv run ruff check --fix sie.py && uv run ruff check sie.py`. The deploy pipeline gates on this; pre-linting in-sandbox avoids the gate failing on the user's machine.
3. Tests — `uv run pytest tests/ -v`. The test suite is the executable form of the code contracts in the skill files — if a test fails, the test name usually points to the function under test.
4. Shebang check — `head -1 sie.py` must print `#!/usr/bin/env python3` (not empty). The tests don't catch this (they import `sie` as a module). Verify with `chmod +x sie.py && ./sie.py --version` — should print `sie <VERSION>`. See `MEMORY.md` "Leading empty line breaks shebangs" for the lesson.
5. Trace one user action — if the patch changed any logic (not just formatting), trace one user action through the changed code path to confirm it reaches the expected outcome.

---
Post-turn updates

Apply after every turn, regardless of whether a code patch was made. The user may push at any moment without notifying the agent — on the off chance that any turn is the last before a push, the documentation artifacts must already be current.

1. Update `MEMORY.md` when:
    - You finished a new, distinctive set of code changes — future sessions need to know what changed and why.
    - A code change failed in a way that would surprise a fresh model in a new chat if it wasn't documented — failures are the most valuable `MEMORY.md` entries because they prevent re-discovery.
    Apply the update inline — produce the updated `MEMORY.md` in `download/` for the user to apply. Do not propose it as a draft for the user to approve. If the turn produces no distinctive changes worth remembering, skip this.
2. Update a skill when a patch changes the architecture the skill documents. Don't update a skill for a pure bug fix that doesn't change the documented architecture. Apply the update inline (deliver the updated skill file in `download/`). Check cross-skill consistency: when updating one skill, check whether existing skills already cover the pattern — if they do, update them rather than just adding to `MEMORY.md`.
3. Download copy — see the `delivery` skill → "Workflow (high-level)" for the full deliver-zip protocol. In short: copy only the files you created or updated this turn to `download/` with flat `__`-encoded names, run `prepare.sh` to zip into `deliver.zip`, then remove the loose files. The `__` separator is unambiguous — single hyphens in real filenames (`code-quality`, `input-forms`) are preserved. See the `delivery` skill for the full naming convention.

---
Versioning

The user states the current version in their first chat message, either directly ("Current version: 1.1.0") or by referencing `sie.py`'s `VERSION` constant. If they don't state it, derive it from `sie.py` (line 1 has `VERSION = "1.1.0"`) or from `pyproject.toml`'s `version` field. When the user requests a version change, apply semver rules:

- Same: 1.1.0 → 1.1.0
- Patch: 1.1.0 → 1.1.1
- Minor: 1.1.0 → 1.2.0
- Major: 1.1.0 → 2.0.0

Patch releases for bug fixes. Minor bumps for new features that change the CLI surface or output format. Major bumps for breaking changes. The version is hardcoded at the top of `sie.py` as `VERSION = "1.1.0"` — update in lockstep with `pyproject.toml` and `README.md`.

Don't change version without an explicit request from the user. Don't substitute version dots with spaces, underscores, or any other character — this applies to filenames passed to all tools.

---
Cross-references

- `delivery` — behavioral rules for the chat.z.ai web channel (applies every turn) + the delivery workflow (prepare → zip → deploy) + sandbox vs. user-side environment table. The delivery scripts (`prepare.sh`, `deploy.sh`, `setup-sandbox.sh`) live at `skills/delivery/scripts/`.
- `code-quality` — patterns to follow and pitfalls to avoid when writing Python in `sie.py` (cognitive complexity, redundant exceptions, mutable defaults, KEEP_FIELDS, URL parsing, bash script patterns for the delivery scripts)
- `sonarqube-workflow` — `sie` Markdown report triage + sandbox API fallback + SonarCloud/CodeQL environment details
- `skill` — when to create or update skills vs `MEMORY.md` entries; consolidation direction protocol
- `ai/README.md` — the current Espanso trigger list + chat.z.ai caveats + OMP harness note
- `MEMORY.md` — durable gotchas and project invariants
- `CONTRIBUTING.md` — human-facing dev setup + web chat deploy pipeline reference
