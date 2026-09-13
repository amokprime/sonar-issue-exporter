# sonar-issue-exporter

### AI Disclosure and Disclaimer
I am neither a developer nor affiliated with Sonar. The Python scripts in this repo are vibe-coded with [DeepSeek](https://chat.deepseek.com/) and [Z.ai](https://chat.z.ai/). Prompt history for the scripts is in [/archive](https://github.com/amokprime/sonar-issue-exporter/tree/main/archive). I have only tested the scripts with GitHub on Windows 11 (0.1.0-0.2.0) and Fedora 44 KDE (0.2.1+, including the 1.0.0 single-file refactor). They might also work for repos on GitLab, Bitbucket, and Azure Cloud on any OS where Python is supported.

sonar-issues-exporter is not an official Sonar product. It is a client tool that fetches data from the SonarQube Cloud [Web API](https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api). Users must have their own authorized SonarCloud account and API token. Rule descriptions and educational content are the intellectual property of SonarSource SA. This tool does not bundle or redistribute SonarSource content (see .gitignore).

### About

sonar-issue-exporter is a CLI tool to download Sonar issues and CodeQL code scanning alerts. These issues can be generated automatically by SonarCloud and CodeQL GitHub Actions to quality control vibecoded projects like this one.

## Setup

### SonarCloud GitHub Action
1. Add a SonarCloud analysis GitHub workflow to your GitHub repo. Follow the instructions in the `sonarcloud.yml` template.
2. Go to your repo Settings/Rules/Rulesets → Require code scanning results and add SonarCloud. It should now scan before any commit.
3. For private projects, go to your SonarQube Cloud account → Security (shield icon) in left ribbon → Generate Tokens → Enter some name you'll remember → Copy the token and save it to a password manager like KeepassXC
### CodeQL analysis
1. In your GitHub repo settings -> Security and quality -> Advanced Security -> enable the default CodeQL analysis. You can also setup a GitHub Actions workflow with a `.yml` template.
2. Install `gh` in a terminal and login to your GitHub account.

### Installation

Run this on Linux:
```sh
mkdir -p ~/.local/bin && \
  curl -fsSL https://raw.githubusercontent.com/amokprime/sonar-issue-exporter/main/sie.py \
  -o ~/.local/bin/sie && chmod +x ~/.local/bin/sie
```

If `~/.local/bin` isn't on `PATH` yet, add `export PATH="$HOME/.local/bin:$PATH"` to your `~/.bashrc` (or `~/.zshrc`, or `set -gx PATH ~/.local/bin $PATH` in fish). The troubleshooting section below covers this in more detail.

Then check:
```sh
sie --version   # should print: sie 1.1.0
sie --help      # full usage + examples
```

### Configuration

To see the "Why" or "How to fix it?" Sonar messages, set your API key in your shell environment:
```sh
# fish (~/.config/fish/config.fish):
set -gx SONAR_API_KEY (kwallet-query -f ksshaskpass -r Sonar kdewallet | string trim)

# bash/zsh (~/.bashrc or ~/.zshrc):
export SONAR_API_KEY="your-token-here"
```

`sie` checks `SONAR_API_KEY` first (preferred), then `SONAR_TOKEN` (SonarQube convention fallback). No file-based config — keys must be in the shell environment.

For public projects, you can skip the token entirely — `sie` will run in "public-project mode" and still enumerate issues and facets. The why/how rule-rationale subsections will render placeholders (rule rationale requires `api/rules/show`, which needs auth). See [docs/auth-boundary.md](docs/auth-boundary.md) for the full auth boundary table.

#### Updating

**If you installed via the one-liner** (no clone), just re-run it to pull the latest `main`:
```sh
curl -fsSL https://raw.githubusercontent.com/amokprime/sonar-issue-exporter/main/sie.py \
  -o ~/.local/bin/sie && chmod +x ~/.local/bin/sie
sie --version           # confirm new version
```

**If you installed from a clone**, pull and reinstall:
```sh
cd /path/to/sonar-issue-exporter
git pull
install -Dm755 sie.py ~/.local/bin/sie   # or: cp sie.py ~/.local/bin/sie && chmod +x ~/.local/bin/sie
sie --version           # confirm new version
```

## Usage

### Quick start

The most common commands for public projects (no `gh` auth needed):
```sh
sie amokprime/sonar-issue-exporter                    # author/reponame fetch issues → issues.md
sie -s amokprime/sonar-issue-exporter                 # quick triage → stdout (no file)
sie 'https://github.com/amokprime/linebyline/pull/11' # GitHub PR URL
sie -c amokprime/linebyline                           # clean export (drops licensed Why/How)
sie -d                                                # diagnose token env var
```

All of the above work without `gh` installed. The input can be a SonarCloud URL, GitHub URL, fuzzy `owner/repo[/branch]`, or (from inside a repo) a single-token shortcut. See [docs/input-forms.md](docs/input-forms.md) for the full input-form reference.

### Full reference

```sh
sie -h                 # short usage
sie -v                 # version
sie -s [INPUT]         # cheap triage -> stdout (no file)
sie [INPUT] [OUTPUT]   # full export -> Markdown
sie -c [INPUT] [OUTPUT]  # clean export (drops licensed Why/How sections)
sie -m [FOLDER] [OUTPUT]  # migrate a 0.2.x issues folder
sie -d                 # diagnose token env var visibility
```

**Quick triage** (`-s` / `--summary`): fetches facets + total count only (one API call), prints a compact rule × severity × count table to stdout, writes no file. No auth required for public projects.

**Clean mode** (`-c` / `--clean`): silently drops the Why/How rule-rationale subsections from the Markdown output — no placeholder, no warning. Use this to avoid pushing possibly-licensed Sonar content to a chat. See [docs/clean-mode.md](docs/clean-mode.md).

**Local-folder migration** (`-m` / `--migrate`): converts an existing 0.2.x per-issue folder export to the single-file Markdown format, nondestructively. See [docs/local-migration.md](docs/local-migration.md).

**Output paths**: when no explicit output path is given, `sie` writes to `scratch/` (if at a git root), else cwd (if in a git project), else `~/Downloads/` (last resort). Auto-incrementing: `issues.md` → `issues1.md` → `issues2.md` (v1.1.0: renamed from `sonar-issues.md` since the file may contain CodeQL alerts, SonarCloud issues, or both). See [docs/output-paths.md](docs/output-paths.md) for the full resolution rules and positional disambiguation.

### Output format

A single Markdown file. When both SonarCloud and CodeQL have open findings, the file has a combined layout with a project-level header and one `## <Source>` section per source. When only one source has findings, the simpler single-source layout is used (no parent `## <Source>` heading).

```markdown
# Issues — <project> (<scope>)

Generated: 2026-09-12 23:48 UTC
Source: `<input — the original URL, fuzzy string, or local path>`
Total: 5 issue(s) across 2 source(s), 3 rule(s)  (SonarCloud: 4, CodeQL: 1)
Token: present | absent

---

## SonarCloud Issues

### Summary

| Severity   | Count |   | Type          | Count |
|------------|-------|---|---------------|-------|
| CRITICAL   | 4     |   | CODE_SMELL    | 4     |

Top rules:
- `python:S3776` — 4×

---

### Rule: `python:S3776` — <rule name>

Severity: CRITICAL: 4 · Type: CODE_SMELL: 4 · 4 instance(s)

#### Why
<rule rationale — fetched via api/rules/show when token present, else placeholder>

#### How to fix
<fix guidance — fetched via api/rules/show when token present, else placeholder>

#### Instances

| File | Line | Message | Key | Status |
|------|------|---------|-----|--------|
| `sie.py` | L128 | Refactor this function... | `AaBprfwD68fRE0gxBFj3` | OPEN |

Deep links: `https://sonarcloud.io/project/issues?open=<KEY>&id=<PROJECT>`

---

## CodeQL Alerts

### Summary

| Severity   | Count |   | Type          | Count |
|------------|-------|---|---------------|-------|
| WARNING    | 1     |   | CODE_SMELL    | 1     |

Top rules:
- `py/incomplete-url-substring-sanitization` — 1×

---

### Rule: `py/incomplete-url-substring-sanitization` — <rule name>

Severity: WARNING: 1 · Type: CODE_SMELL: 1 · 1 instance(s)

#### Why
<CodeQL rule help — bundled in the alert JSON, no token needed>

#### How to fix
(SonarCloud's `api/rules/show` did not return separate fix guidance; see Why above.)

#### Instances

| File | Line | Message | Key | Status |
|------|------|---------|-----|--------|
| `sie.py` | L1309 | Substring check on unparsed URL. | `codeql:5` | OPEN |

---
```

### Troubleshooting

#### `sie --version` prints nothing / "command not found"
- Check `~/.local/bin` is on your `PATH`: `echo $PATH | grep -o '\.local/bin'`
- If missing, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or `~/.zshrc`).

#### Why/how sections show "⚠ Set SONAR_TOKEN" placeholder
- Rule rationale (`api/rules/show`) requires auth. Set `SONAR_API_KEY` (or `SONAR_TOKEN` as fallback) in your shell environment.
- Public-project issue enumeration works without a token — only the why/how content is gated.

#### `sie pr` errors with "requires the GitHub CLI (`gh`)"
- The `pr` shortcut invokes `gh pr list` to find the most recent open PR. Install `gh` from https://cli.github.com, then `gh auth login`. In other words, it only works on your *own* repos.
- For a specific PR without `gh`, use the GitHub PR URL form: `sie https://github.com/owner/repo/pull/11`.

#### `sie` (no arg) errors with "Could not discover GitHub repo info from cwd"
- `sie` tried `./package.json`, `./pyproject.toml`, and `git remote get-url origin`, and none yielded a GitHub URL.
- Either run `sie` from inside a repo, or pass an explicit input: `sie amokprime/linebyline` or `sie 'https://...'`.

#### Full export shows "0 issue(s)" but I see issues on the SonarCloud UI
- Check the URL's `issueStatuses=` param — `sie` defaults to `OPEN` if not set. Closed issues won't appear unless you pass `&issueStatuses=OPEN,CONFIRMED,CLOSED` in a SonarCloud API URL.
- For PR-scoped exports, make sure `&pullRequest=N` is in the URL — main-branch issues won't show up on a PR-scoped fetch.
- For branch-scoped exports, the branch name must match what SonarCloud indexed. Check the SonarCloud UI for the exact branch name (case-sensitive).

#### Single-issue URL (`?open=<KEY>&id=<PROJECT>`) shows the Focal Issue callout but no instances below
- This means the focal issue lookup returned 0 results — likely the auth-boundary case (single-issue `?issues=<KEY>` lookup requires auth). `sie` automatically falls back to fetching the whole project's OPEN issues; if that also returns 0, the issue may be CLOSED or on a different branch/PR than the URL implies.

### Token detection issues (KWallet, fish shell, "absent despite being set")
See [docs/troubleshooting-token.md](docs/troubleshooting-token.md) for the `sie -d` diagnostic and common causes (env var not exported, KWallet locked, non-shell contexts, universal var not loaded).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the web chat deployment pipeline, and agent-facing docs.

## License

MIT — see [LICENSE](LICENSE).
