Local OMP harness rules for sonar-issue-exporter. The chat.z.ai sandbox has a different ruleset — see `skills/delivery/SKILL.md` for the cloud rules (web-channel + delivery workflow) and `skills/sonar-issue-exporter/SKILL.md` for onboarding + workflow.
### Direct edits you make
- The user pushes directly to `main` (no staging branch, no PR-based review loop). Don't push for them — make edits directly in the working tree using the hashline edit tool, and let the user review `git diff` and push.
- If you make local edits to tracked files, leave them in the working tree — don't stage commits. The user reviews `git diff` and decides what to push.
- If you create new files, leave them untracked — `git add -N <file>` is OK to mark them as intent-to-add for the diff, but don't `git commit`.
- Don't run `git reset --hard` or `git clean -fdx` — those destroy uncommitted local changes. The user may have local work in progress that isn't reflected in the last commit.
### Tests and lint
- The full pytest suite is small (~182 specs, <1s) — run it end-to-end before declaring a patch done: `uv run pytest tests/ -v`.
- `uv run ruff check --fix sie.py` (autofix safe violations) followed by `uv run ruff check sie.py` (gate — zero findings required). The deploy pipeline runs the shared lint gate (Shellcheck + Ruff via `skills/code-quality/scripts/lint_gate.sh`), so pre-linting avoids the gate failing on the user's machine.
- The shebang check is critical — `head -1 sie.py` must print `#!/usr/bin/env python3` (not empty). Tests import `sie` as a module and don't catch a missing shebang; only `chmod +x sie.py && ./sie.py --version` does.
### Blocked paths (read-only inside this sandbox)
- `.omp/` is read-only as a harness self-protection measure. Stage edits to `.omp/AGENTS.md`, `.omp/RULES.md`, or `.omp/config.yml` under `scratch/` and hand the user a copy command.
- `.omp/skills/` symlinks can't be created from inside this sandbox (`ln -s` is blocked). The user runs `bash skills/delivery/scripts/setup-omp-skills.sh` locally to create or refresh the symlinks after a deploy.
### When to defer to chat.z.ai
- For any build/test/review loop on `sie.py` or `tests/`, defer to the chat.z.ai sandbox — it has the project skills auto-loaded and the `code-quality` / `sonarqube-workflow` skills at hand. You should only patch `sie.py` here when the issue is reproducible only locally (e.g. a fish-shell token visibility quirk, a `gh` auth edge case, a SonarCloud API behavior the sandbox can't reach).
- For SonarCloud issue triage, defer to chat.z.ai — the `sonarqube-workflow` skill walks through the triage protocol. If you do triage here, run `sie` locally with `SONAR_API_KEY` set to get the why/how rule rationale, then read the resulting `issues.md` and triage.

### Skill maintenance
- When you update a skill in `skills/<name>/SKILL.md`, the corresponding `.omp/skills/<name>` symlink (once created by `setup-omp-skills.sh`) points to the same file, so the update is automatically visible to you. No separate OMP-side skill copy.
- When you create a new skill, run `bash skills/delivery/scripts/setup-omp-skills.sh` after a deploy to add the new symlink.
- The `skill` skill (`Skill(command="skill")` via the auto-loaded description, or `skills/skill/SKILL.md` directly here) covers the consolidation direction protocol — when in doubt about whether something belongs in a skill vs `MEMORY.md` vs `AGENTS.md`, consult it.