---
name: asd-ste100
description: Rewrite human-facing technical documentation in Simplified Technical English (ASD-STE100). Use this skill when writing or revising README files, CONTRIBUTING guides, docs/ reference pages, or any prose a human reader will consume. Triggers when the user mentions STE, ASD-STE100, Simplified Technical English, plain-language rewrite, controlled English, or when human-facing docs have dense, hedged, or AI-style prose. Applies structural rules (active voice, short sentences, one instruction per sentence, no semicolons, no phrasal verbs, no nominalization) in STE-flavored mode — the lexical one-word-one-meaning rule is advisory for prose, not a hard lockdown. Excludes agent-facing files (AGENTS.md, skills/, .omp/) and archive/ transcripts.
---
ASD-STE100 is a controlled-language standard built by the aerospace and defense industry to stop maintenance technicians from misreading English instructions. The standard removes two sources of misreading: words with more than one meaning, and sentences with more than one possible structure.

This skill applies that discipline to human-facing documentation in the sonar-issue-exporter project: `README.md`, `CONTRIBUTING.md`, `docs/*.md`, `scripts/README.md`, `tests/README.md`. It does NOT apply to agent-facing files (`AGENTS.md`, `skills/`, `.omp/`) or `archive/` transcripts.

---
When to use this skill

- You write or revise a human-facing doc (README, guide, reference page).
- A doc has clear signs of AI writing: dense noun clusters, hedge stacking, synonym rotation, marketing adjectives, run-on sentences.
- The user asks for a "plain-language rewrite" or "STE rewrite."

Do NOT apply this skill to:
- `AGENTS.md`, `MEMORY.md`, `skills/`, `.omp/` — agent-facing files with their own conventions.
- `archive/` — historical transcripts, off-limits.
- Code comments — the `delivery` skill's comment-density rules apply there.
- Creative or marketing copy — STE is flat and literal, not persuasive.

---
Two modes

Strict — procedures, error messages, tool descriptions, safety text. Apply every rule including the hard length caps and one-word-one-meaning discipline. Not used for SIE docs (they are prose, not procedures).

STE-flavored — READMEs, guides, reference pages, explanatory prose. Apply the structural rules in full. Treat the lexical rules as advisory. Keep sentence length caps, active voice, simple tenses, no phrasal verbs, no semicolons, no nominalization, no marketing adjectives. Drop the one-word-one-meaning lockdown: prose needs some range, and a strict rewrite reads as a personality transplant.

SIE human-facing docs use STE-flavored mode.

---
Core rewrite rules

Structural rules — apply these

| Rule                         | Do                                              | Don't                                                                                                                   |
| ---------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Active voice                 | "The agent deletes the file."                   | "The file is deleted (by the agent)." — unless the actor is genuinely unknown                                           |
| No phrasal verbs             | "Remove the panel." / "Start the job."          | "Take off the panel." / "Spin up the job."                                                                              |
| One instruction per sentence | "Open the file. Read line 3."                   | "Open the file and read line 3, then check if it matches."                                                              |
| Sentence length              | 25 words or fewer for descriptions              | Long compound or subordinate-clause sentences                                                                           |
| No semicolons                | Split into separate sentences                   | Any semicolon — STE bans the mark outright                                                                              |
| Noun clusters                | 3 words or fewer stacked as a noun phrase       | 4+ word noun stacks                                                                                                     |
| No ellipsis                  | Keep subject, verb, and article explicit        | Drop words to save space                                                                                                |
| Zero vocative                | "Run the script." / "Set the env var."          | "You can run the script." / "The user should set the env var." — reserve "you" for deliberate first-person author voice |
| Keep modality                | "The request may have failed." stays "may have" | Promote a hedge to a fact                                                                                               |
| Paragraph limits             | One topic per paragraph, 6 sentences or fewer   | Multi-topic paragraphs                                                                                                  |
| Lists for sequences          | Use a numbered or bulleted list for 3+ steps    | Bury a sequence inside one prose sentence                                                                               |

Lexical rules — advisory for STE-flavored mode

| Rule | Do | Don't |
|---|---|---|
| One word, one meaning | Pick one verb for one action and reuse it | Rotate synonyms for the same idea |
| One part of speech per word | "Apply oil to the valve" (oil = noun) | "Oil the valve" (oil = verb) |
| Verb, not noun | "Analyze the log." | "Perform an analysis of the log." |
| Domain terms | Keep necessary technical nouns, define them once | Use jargon without defining it |

Simple tenses

STE permits simple present, simple past, simple future, imperative, infinitive, and past participle as adjective. It excludes present perfect and other compound forms: "we received the report", not "we have received the report".

Where the compound form carries information the simple form cannot — current relevance, or a hedge as in "may have failed" — keep it and flag the departure. Elsewhere, follow the rule.

---
Scan checklist

Scan for these six habits before you rewrite:

1. Synonym rotation — the same thing gets several names in one document ("the user", "the customer", "the client"). Fix: pick one name, use it every time.
2. Hedge stacking — helper verbs and qualifiers pile up until the sentence asserts nothing ("it is important to note that this may potentially help to improve"). Fix: state the claim, or delete it.
3. Nominalization — an action frozen into a noun ("perform an analysis of", "provides assistance to"). Fix: use the verb ("analyze", "helps").
4. Marketing adjectives — words that claim quality instead of showing it: seamless, robust, powerful, cutting-edge, effortless, blazing-fast. Fix: delete, or replace with the measurement that earns the claim.
5. Run-on sentences — several ideas joined by semicolons or em dashes. Fix: one idea per sentence.
6. Soft phrasal verbs — spin up, reach out, dive into, kick off. Fix: use the single plain verb (start, contact, read, begin).

---
Process

1. Read the input text once for meaning. Do not start rewriting before you understand what it must still say afterward.
2. Walk it sentence by sentence. Flag every rule violation from the tables above.
3. Rewrite each flagged sentence to fix the violation while preserving the original meaning. If a rewrite would drop necessary precision (a safety condition, a scope qualifier, a number), keep the longer phrasing and flag it.
4. Check modality before you commit to a rewrite. Hedges ("may", "could", "sometimes") carry the author's confidence. A shorter sentence that upgrades a hedge to a fact is not a simplification — it is a different claim.
5. Never add a fact the source did not state. A rewrite that reads better because it supplies a cause or a frequency has stopped being a rewrite.
6. For a mechanical first pass, run `scripts/ste-lint.py` (stdin or file args). It checks semicolons, sentence length, phrasal verbs, nominalization, marketing adjectives, synonym rotation, dangling conjunctions, passive voice, and compound tenses. It never flags hedges or modality.

---
Linter

`skills/asd-ste100/scripts/ste-lint.py` — a deterministic, stdlib-only Python linter for the structural rules. Run it on human-facing `.md` files before delivering:

```sh
python3 skills/asd-ste100/scripts/ste-lint.py README.md CONTRIBUTING.md docs/*.md
```

The linter exits 1 when hard violations exceed the baseline (default 0). Advisory findings (passive voice, compound tenses) never fail the run. Use `--baseline N` to tolerate N hard violations when adopting on existing docs. Use `--disable rule1,rule2` to silence named rules.

The linter never flags hedges or modality: confidence is content, not style. "May have failed" passes clean.

---
Integration with the delivery pipeline

`skills/delivery/scripts/prepare.sh` runs `ste-lint.py` on all `.md` deliverables in `download/` before zipping. The check is advisory — it prints findings but does not block the zip. Fix the findings before delivering when you can, but do not block a delivery on a pre-existing doc that has not been swept yet.

---
Cross-references

- `delivery` — comment-density rules for code files (different from STE, which is for prose).
- `code-quality` — code quality patterns for Python and bash (not prose).
- `skill` — when to create or update skills vs `MEMORY.md` entries.
