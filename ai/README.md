---
summary: This folder holds human-facing reference docs for the chat.z.ai web-channel workflow (and the OMP harness option for local Copilot-like tasks). Agent-facing context files live at repo root (AGENTS.md, MEMORY.md, skills/, scripts/, .omp/) — not in ai/.
links:
  - "[[AGENTS.md]]"
  - "[[scripts/espanso.yml|Espanso snippets]]"
  - "[[.omp/AGENTS.md|OMP harness context]]"
---
#### Working with [chat.z.ai](https://chat.z.ai/) (GLM)

Caveats to work around:
- I have noticed as many as 2k ads being blocked by uBlock Origin (you can install this on Helium and Microsoft Edge if not on Firefox)! It keeps ramping up over time, possibly causing unresponsiveness even in Chromium browsers. It may help to close the browser window and reopen the page (just reloading or closing the browser tab isn't always enough).
- A captcha slider randomly pops up sometimes while the agent works—avoid going fully AFK with the browser closed.
- Sandboxes historically expired after 2 hours. Typing something before it expires resets the timer to another 2 hours. Sometimes the agent can recover generated files anyway. Try sending a message like "Continue" to resume a cutoff chat. More recent (Sep 2026) chat sessions don't seem to occupy a specific sandbox that appears in web UI settings.
- Uploads may fail to update if certain filenames like file.md and Memory.md are re-uploaded without renaming them or zipping them in a uniquely named folder. If uploads generally fail, upload a file or zip to https://tmpfiles.org and share the link. The agent can download it into its sandbox with `curl`.
- Downgrade to a lower model, chats failing to submit or load or timing out, during peak hours. Use the 'previous flagship model' during off-peak hours to mitigate these issues.
- The "All files in task" download widget can go stale or disappear after multiple sandbox-side file operations. The agent will touch `download/` to force a refresh, and provide a fallback https://tmpfiles.org link in case that doesn't work.

The website auto-loads project skill descriptions (from `/home/z/my-project/skills/<name>/SKILL.md`) into the agent's `available_skills` list — but does NOT auto-load root `AGENTS.md` or `MEMORY.md`. For `AGENTS.md` and `MEMORY.md`, use the Espanso snippets in `scripts/espanso.yml` (`:scm`, `:sco`, `:ssk` triggers) or copy paste to insert clone + read instructions.

chat.z.ai also had a more recent bug where the same named zip file can persist across sandboxes. This prevents the agent from reading future uploaded zips of the same name. So I use [scripts](https://github.com/amokprime/sonar-issue-exporter/tree/main/scripts/README.md) to generate the zip files with a unique name.

#### OMP harness option

This repo has a `.omp/` folder with a skeleton config for the [OMP](https://github.com/iomeg/omp) harness — a local Copilot-like agent that uses free API providers (the configured default is DeepSeek V4.1 Flash via Token Harbor, but expand to paid providers if you have a subscription). Use OMP for tasks that benefit from a local checkout:

- Troubleshooting bugs that cannot be reproduced in the chat.z.ai sandbox (e.g. fish-shell token visibility, `gh` auth edge cases, real-CWD output path resolution).
- Patching SonarCloud issues when the chat.z.ai session is 15+ turns in (avoid burning context).
- Updating stale documentation or agent context files.

OMP-specific context lives in `.omp/AGENTS.md` (project structure, environment) and `.omp/RULES.md` (patch hygiene, blocked paths, when to defer to chat.z.ai). The `.omp/skills/` folder contains relative symlinks to `../../skills/<name>` so OMP auto-loads the same skills as chat.z.ai — the symlinks point to a subset of skills relevant to OMP (not all skills, since OMP edits files directly).

#### Templates

`ai/templates/` holds blank Obsidian transcript templates for archiving chat sessions:
- `chat.z.ai.md` — the GLM chat.z.ai session format (frontmatter + 20-turn skeleton).
- `OMP.md` — minimal OMP frontmatter (OMP fills in its own transcript format at session start, so the template is just the frontmatter).

Per-version archives go in `archive/<version>/` (e.g. `archive/1.1.0/1.1.0.md`). Don't go back and edit transcripts; do update standalone docs.
