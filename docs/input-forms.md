## Input forms

`sie` accepts a flexible set of input forms. The first positional arg is resolved in this priority order:

1. [SonarCloud URL](#1-sonarcloud-url-ui-or-api-form)
2. [GitHub URL](#2-github-url-auto-converts-to-sonarcloud-api-url)
3. [Fuzzy `owner/repo[/branch]`](#3-fuzzy-ownerrepobranch)
4. [Single-token shortcuts](#4-single-token-shortcuts-from-inside-a-repo)
5. [No arg](#5-no-arg-from-inside-a-repo)

---

### 1. SonarCloud URL (UI or API form)

The most explicit form — pass through any SonarCloud URL.

```sh
# UI URL, project scope (main branch):
sie 'https://sonarcloud.io/project/issues?id=amokprime_linebyline'

# UI URL, single issue (renders a Focal Issue callout at the top):
sie 'https://sonarcloud.io/project/issues?open=AaBprftR68fRE0gxBFjx&id=amokprime_linebyline'

# UI URL with extra params (sinceLeakPeriod, issueStatuses=OPEN,CONFIRMED — all passed through):
sie 'https://sonarcloud.io/project/issues?id=amokprime_linebyline&pullRequest=11&issueStatuses=OPEN,CONFIRMED&sinceLeakPeriod=true'

# API URL (advanced; passed through with ps=500 normalization):
sie 'https://sonarcloud.io/api/issues/search?componentKeys=amokprime_linebyline&issueStatuses=OPEN'
```

The mapping for UI URLs: `?id=<PROJECT>` becomes `?componentKeys=<PROJECT>` (renamed); `?open=<KEY>` becomes the `focal_key` descriptor field (consumed, not passed through); everything else passes through verbatim.

---

### 2. GitHub URL (auto-converts to SonarCloud API URL)

Lets you copy a URL straight from the GitHub UI. `sie` derives the SonarCloud project key as `<owner>_<repo>` (the convention for GitHub-integrated SonarCloud projects) and maps the path to the right SonarCloud scope:

| GitHub path | SonarCloud scope |
|---|---|
| `/owner/repo` | main branch |
| `/owner/repo/pull/<N>` | `?pullRequest=<N>` |
| `/owner/repo/tree/<branch>` | `?branch=<branch>` |
| `/owner/repo/blob/<branch>/...` | `?branch=<branch>` |
| `/owner/repo/commit/<sha>` | not supported (SonarCloud indexes branches/PRs, not arbitrary SHAs) |

```sh
sie 'https://github.com/amokprime/linebyline/pull/11'         # -> ?pullRequest=11
sie 'https://github.com/amokprime/linebyline/tree/staging'    # -> ?branch=staging
sie 'https://github.com/amokprime/linebyline'                 # -> main branch
```

GitHub branch names can contain slashes (e.g. `feature/sync-rewrite`). The `/tree/<branch>` URL form preserves the full branch name across the slash; the `/blob/<branch>/<path>` form has only one segment after `/blob/` as the branch (the rest is the file path).

---

### 3. Fuzzy `owner/repo[/branch]`

Shorthand for when you know the project but don't want to type a full URL.

```sh
sie amokprime/linebyline            # main branch
sie amokprime/linebyline/staging    # staging branch
```

---

### 4. Single-token shortcuts (from inside a repo)

When run from inside a repo (i.e. cwd has a `package.json`, `pyproject.toml`, or is a git checkout), `sie` discovers the project automatically and the input can be a single token:

| Token | Resolves to |
|---|---|
| `pr` | most recent open PR (via `gh` CLI — requires `gh auth login`) |
| `main` | main branch of cwd's repo |
| `<branch-name>` | that branch of cwd's repo (e.g. `sie staging`) |

```sh
cd ~/code/linebyline
sie pr        # most recent open PR (via `gh pr list --state open --limit 1`)
sie main      # main branch
sie staging   # staging branch
```

The `pr` shortcut requires the GitHub CLI (`gh`), which is typically not installed in agent sandboxes or non-developer environments. For a specific PR without `gh`, use the GitHub PR URL form: `sie https://github.com/owner/repo/pull/11`.

---

### 5. No arg (from inside a repo)

```sh
cd ~/code/linebyline
sie           # main branch of cwd's repo (same as `sie main`)
```

---

### Repo discovery (for single-token / no-arg modes)

`sie` discovers the GitHub owner/repo from cwd using these sources, in priority order:

1. `./package.json` → `repository.url` field (JS projects)
2. `./pyproject.toml` → any `github.com/owner/repo` URL (Python projects; regex-based parse so no `tomllib` dependency — keeps Python 3.10 support)
3. `git remote get-url origin` (catch-all for any git checkout)

If none of these yield a GitHub URL, `sie` errors with a helpful message asking you to pass an explicit URL or `owner/repo`.
