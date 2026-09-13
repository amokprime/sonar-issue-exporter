---
name: web-channel
description: Behavioral rules for the chat.z.ai Agent web channel. Use this skill on every turn of every session — not just at onboarding — because the web channel is the only interaction surface and the agent is most likely to forget these rules in later turns as context compacts. Also use when the user mentions chat.z.ai, download folder, web chat, Agent mode, uploads, or when the agent is unsure about file visibility, output format, or comment density.
---

The chat.z.ai Agent web channel imposes constraints that differ from a local CLI or IDE. The agent cannot see the user's filesystem directly; deliverables must be copied to `download/` for the user to retrieve. The agent's context window compacts over long sessions, making early-turn instructions less reliable later — this skill exists to be re-read when that happens.

---

File visibility

The user can only see files inside `/home/z/my-project/download/`. Everything else (project tree, scripts, temp files) is invisible to them.

- Copy every deliverable to `download/` — the user cannot access other folders.
- Avoid subdirectories inside `download/` — the user cannot see them. Put files directly in `download/` or zip them.
- Don't clutter `download/` with compiled temporary files like `*.pyc` or `__pycache__/`. After running Python scripts, clean up.
- For multi-file sessions, the deliver workflow is preferred: stage files in `download/` with flat hyphenated names (e.g. `ai/chat.z.ai/MEMORY.md` → `ai-chat.z.ai-MEMORY.md`), include `deploy.sh`, then run `prepare.sh` to zip into `deliver.zip` and remove the loose files. The user downloads `deliver.zip`, not the individual files. Keep loose files in `download/` only when `prepare.sh` hasn't run yet.
- **Keep `download/` clean between turns.** If the user reports "I only see 3 files but you said you wrote 4", first verify the file exists at `download/<name>` via `ls -la /home/z/my-project/download/`. If it's there, it's an IM gateway sync issue — re-touch the file (`cp -p file file && rm file && cp file file`) to bump the mtime, or just mention it explicitly in chat. If it's NOT there, you forgot to write it — fix that first.
- Avoid spaces in filenames. The download system URL-encodes spaces as `+`, which can cause "Failed to download file" errors. Use hyphens or underscores instead.

---

Input handling

- Stop immediately to request any missing uploads. Don't infer their contents — if the user refers to a file you haven't seen, ask for it.
- Read docs and manifests (i.e. `*.md`, `pyproject.toml`, `package.json`) before code (i.e. `*.py`, `*.sh`). Documentation describes intent; code is the implementation. Reading docs first prevents misinterpretation.
- The Repomix archive the user uploads is a snapshot — paths appear in `<directory_structure>` even if their contents were dropped by `.gitignore`. If the agent needs a file that isn't in the pack, ask the user to re-export or paste it.

---

Output format

- Don't generate Office documents or PDFs. Just output to chat in English.
- Implement the strongly dominant solution as a drop-in code file for the user to run and test. Only stop and ask if the user's intention or environment are unclear, or if multiple competing solutions exist.
- For multi-file deliverables, use the zip pattern: stage everything in a working directory (`/home/z/my-project/work/staging/<project>/`), then `zip -r download/<project>-<version>.zip staging/<project>/` (or similar) so the zip preserves the directory structure the user expects.

---

Comment density

Avoid 3+ consecutive lines of source comments, both inline and multiline blocks like Python's `""" """`. Instead:

- Pair each non-trivial `name.ext` source file with a `name.md` readme, explaining intent, usage, suggested core patches (if a workaround or monkeypatch), and known limitations. If such a file is already provided, use it as a starting point.
- For `sie.py` specifically: the top-of-file docstring is the long-form usage doc; the `--help` epilog is the short-form reference; the `README.md` is the human-facing doc; the `ai/chat.z.ai/` files are the agent-facing doc. Don't duplicate across these — each has a different audience.
- Don't use readmes as memory dumping grounds — preserve their structure for naive users and developers.
- Reserve 1-2 line source comments for non-obvious decisions like workarounds, deferred bugs, intentional smells. The `# CRITICAL:` comment in `sie.py`'s `tests/test_input_resolver.py::TestLocalPathSentinelRemoved` is an example — it documents a regression test for a refactor decision that's easy to undo by accident.

---

Context compaction

The agent has a large native context (~1M tokens) but may compact or re-read uploaded files in later turns. This skill is designed to be re-read mid-session when the agent notices it's uncertain about channel rules. If you find yourself re-reading uploaded files, also re-read this skill — the channel rules are just as likely to have been forgotten as the file contents.

For sonar-issue-exporter specifically: when context compacts and you lose track of the current architecture (single-file script, `--migrate` flag, v1.1.0 CodeQL auto-discovery, etc.), re-read `MEMORY.md` first — it's the leanest summary and explicitly flags what training data shadows (e.g. "training data may suggest `uv tool install` — for `sie` 1.0.0+, the install is a single `install -Dm755 sie.py ~/.local/bin/sie").
