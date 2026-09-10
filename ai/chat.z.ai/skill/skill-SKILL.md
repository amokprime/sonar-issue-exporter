---
name: skill
description: Create new skills and update existing ones for the sonar-issue-exporter project. Use this skill whenever you need to create a skill from scratch, revise an existing skill, extract knowledge from MEMORY.md into a skill, or decide whether something belongs in a skill versus MEMORY.md. Also use when planning a skill-creation or skill-update session, or when evaluating whether existing skills need updating based on recent code changes.
---

A skill bakes substantive, reusable knowledge into a persistent artifact so it doesn't bloat MEMORY.md or get lost between sessions. Covers when to create or update skills, how to write them, and how to keep them current.

---

When to create a skill

1. Accumulated patterns — the same class of problem recurs across versions (SonarCloud remediation, URL-parsing edge cases, Markdown-rendering contracts). If you've written the same explanation three times in MEMORY.md, it belongs in a skill.
2. Procedural knowledge — a multi-step workflow the model must follow in a specific order (read API → categorize → assess → plan → deliver). MEMORY.md can note that the workflow exists, but the steps belong in a skill.
3. Domain reference — a catalog of rules, patterns, or gotchas the model needs to look up (SonarCloud false positive categories, URL-form → scope mappings, field-order contracts). Reference tables belong in skills.
4. Architecture documentation — structural knowledge about the codebase that guides where to read and how to patch (which function handles which input form, how the test suite is organized). Changes slowly and is expensive to rediscover each session.

When not to create a skill: one-off bug fixes (stay in MEMORY.md), app-specific state that doesn't generalize, information already well-covered by an existing skill (update that skill instead).

---

MEMORY.md vs skills

MEMORY.md holds: project-specific bugs and their root causes, architectural decisions unique to this project, one-off pitfalls (e.g. "SonarCloud project key is `amokprime_sonar-issue-exporter`, not `sonar-issue-exporter`"), version-by-version change log, known limitations.

Skills hold: general patterns that caused those bugs, reusable architectural patterns, general cautions (e.g. "preserve all extra query params when converting UI URLs to API URLs"), workflow that applies across versions, workarounds and best practices.

If you'd need to explain it to a fresh model in a new session and it's not specific to one app's state, put it in a skill. If it's a historical fact needed to understand why something broke or was changed, keep it in MEMORY.md.

When extracting from MEMORY.md into a skill, prune the MEMORY.md entry to a brief reference. Don't duplicate — MEMORY.md should point to the skill, not restate it.

Within a single version's MEMORY.md section, write one bullet per parallel thread of work, not one bullet per turn. If a thread evolves across multiple turns (fix → regression catch → follow-up), update the existing bullet in-place to reflect the final state rather than appending a new bullet per turn.

---

Anatomy of a skill

File: `topic-SKILL.md` stored in `ai/chat.z.ai/skill/`. Frontmatter `name` matches the file prefix without `-SKILL` (e.g. `name: sonarqube-workflow`). Keep a chat log of skill creation/update sessions in `ai/chat.z.ai/skills/chat/` (not yet present — add when the first session log is needed).

Frontmatter `description` is the primary triggering mechanism — it determines whether the model consults this skill. Write it to be pushy: include both what the skill does and specific contexts for when to use it. List synonyms, related terms, and adjacent scenarios to combat undertriggering.

Weak: "Process SonarCloud issues for sonar-issue-exporter."
Strong: "Process SonarCloud issues for the sonar-issue-exporter project and guide remediation. Use this skill whenever the user asks about SonarQube findings, mentions rules like S3776/S2004/S2681/S5713, needs help deciding whether to fix or mark as Won't Fix, or wants to plan a SonarQube remediation pass before writing any code. Also use when the user uploads a Markdown file produced by `sie`, or when the agent should enumerate issues directly from the SonarCloud public API (no user upload needed for issue enumeration)."

Body structure — organize in the order the model will need it during a typical session:
1. One-paragraph scope statement
2. Step-by-step workflow (if procedural)
3. Reference tables (only for genuine lookup data like rule catalogs)
4. Cautions and gotchas
5. Cross-references to other skills

Keep the body under 500 lines. If approaching this limit, split the domain into sub-skills.

---

Writing style

Explain the why. Don't rely on MUST and NEVER — explain the reasoning so the model understands why something matters and can adapt to situations the skill doesn't explicitly cover.

Weak: "NEVER drop query params when converting UI URLs to API URLs."
Strong: "Preserve all query params from SonarCloud UI URLs through to the API URL — `sinceLeakPeriod`, `rules`, `tags`, etc. The 1.0.0 refactor had a bug where the initial implementation dropped these; the test `test_ui_url_preserves_extra_params` catches this regression."

Generalize, don't overfit. Skills should capture patterns that apply across many invocations. If you're writing instructions that only make sense for one particular function, step back and find the general principle.

Overfit: "When `parse_github_url` sees `/tree/<branch>`, join everything after `/tree/`."
Generalized: "GitHub branch names can contain slashes (e.g. `feature/sync-rewrite`). The `/tree/<branch>` URL form preserves the full branch name across the slash; the `/blob/<branch>/<path>` form has only one segment after `/blob/` as the branch (the rest is the file path)."

Keep it lean. Remove anything that isn't pulling its weight. A shorter skill is read more carefully than a long one.

Use imperative form: "Read the `### Why` section once per rule" (not "The `### Why` section should be read once").

Include concrete examples sparingly — one per non-obvious pattern. Skip examples for things the model already does correctly by default.

Prefer plain structure over decorative formatting. Tables only where they serve as genuine lookup references (e.g. a rule catalog). Bold only for the single most important term in a paragraph.

---

Creating a new skill

1. Identify the domain — look at MEMORY.md entries that share a common theme. If multiple entries about the same domain are verbose and would benefit from a shared reference, that domain needs a skill.
2. Scope the skill — decide what it covers and what it doesn't. Narrow, actionable skills are better than broad, vague ones.
3. Extract from MEMORY.md — for each related entry: if it describes a general pattern, extract the pattern into the skill and prune MEMORY.md to a brief reference; if it describes an app-specific event, keep it in MEMORY.md as-is; if it straddles both, extract the general principle into the skill and keep the specific instance in MEMORY.md.
4. Write the skill — follow the anatomy and writing style above. Draft it, then read it with fresh eyes and improve. Would a fresh model in a new session be able to follow this without additional context?
5. Cross-reference with existing skills — check that the new skill doesn't duplicate or contradict existing ones.
6. Add a test if the skill documents a code contract — e.g. the `code-quality-SKILL.md` "URL parsing — preserve extra params" section has a corresponding test in `tests/test_url_parsing.py`. The test is the executable form of the skill's contract.

---

Updating an existing skill

Update a skill when a patch changes the architecture the skill documents. Don't update for a pure bug fix that doesn't change the documented architecture.

Also update when: a new pattern or gotcha is discovered that the skill should cover; reference data is stale (new SonarCloud rules encountered, new test cases); MEMORY.md entries reveal knowledge that belongs in the skill instead.

Stale reference hygiene — skills that reference specific line numbers go stale quickly. Prefer structural descriptions over exact numbers. Stale-prone: "The `main()` function starts at line 1763." Durable: "The `main()` function is the CLI entry point — find it by grepping for `def main(`."

Add to skill: patterns that recurred or would recur, cautions that prevent real bugs, reference data the model looks up, workflow steps the model must follow. Don't add: app-specific state, one-off fixes that don't generalize, implementation details that change frequently, anything already well-covered by another skill.

---

Evaluating skill quality

1. Triggering accuracy — would the description cause the skill to be consulted when it should be? Would it trigger when it shouldn't?
2. Self-sufficiency — can a fresh model follow the skill without additional context? If the skill says "use the pattern from v1.0.0," it's not self-sufficient.
3. Brevity vs completeness — does every section earn its token cost?
4. No contradiction — does the skill conflict with any other skill or with MEMORY.md?
5. Currency — are version references current? Are deprecated patterns marked as such?
6. Test alignment — if the skill documents a code contract, is there a test that enforces it? If not, add one (the test is more durable than the prose).

---

Lessons from practice

Knowledge offload reduces MEMORY.md bloat. Extracting SonarCloud remediation knowledge from MEMORY.md into `sonarqube-workflow-SKILL.md` turns verbose per-version SonarCloud details into one-line references. MEMORY.md is then a compact historical overview for regression investigation, not a how-to guide.

Tests are the executable form of skill contracts. The `code-quality-SKILL.md` "URL parsing — preserve extra params" section is enforced by `tests/test_url_parsing.py::TestUiUrlParsing::test_ui_url_preserves_extra_params`. When the test fails, the skill explains why the contract matters. When the skill is updated, the test is updated in lockstep.

General patterns emerge from specific incidents. The `code-quality-SKILL.md` "GitHub URL — branch names with slashes" section was extracted from a real bug caught by `tests/test_github_url.py::test_branch_with_slashes_in_name` during the v1.0.0 refactor. No one-off note justified its own section, but the general principle — "branch names can contain slashes; `/tree/` joins everything after, `/blob/` takes only the first segment" — applies to any future GitHub URL handling.