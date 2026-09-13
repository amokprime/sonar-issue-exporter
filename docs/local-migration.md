## Local-folder migration (`-m` / `--migrate`)

If you have an existing 0.2.x export folder (per-issue `L{line}.json` + `why.md` + `how.md` files), `sie -m` can migrate it to a single Markdown file without touching the originals.

### Usage

```sh
# Explicit path:
sie -m '/path/to/linebyline/archive/semantic/0.35.18/issues'
# -> writes issues.md alongside the issues/ folder (nondestructive)

# Auto-discover (no path arg):
cd ~/GitHub/linebyline/archive/semantic/0.37.2/
sie -m
# -> auto-discovers issues/ subfolder, writes issues.md in cwd

cd ~/GitHub/linebyline/archive/semantic/0.37.2/issues/
sie -m
# -> cwd is the issues folder, writes issues.md in parent

# Custom output path:
sie -m '/path/to/issues' ~/my-report.md
```

The `-m` flag is required because a bare path-like positional (e.g. `sie ~/my-report.md`) is interpreted as the **output path** with input defaulting to main of cwd's repo. Without the flag, `sie` has no way to distinguish "this is the migration input" from "this is the output path" — see [output-paths.md](output-paths.md) for the full disambiguation rules.

### Auto-discovery safety

`-m` without a path arg refuses to run in two cases:

- **At a git root** — too many subfolders could match, so `sie` errors rather than guessing. Pass an explicit path.
- **Existing `issues.md` in the output directory** — `sie` refuses to clobber. Pass an explicit output path, or remove the existing file first. (v1.1.0: was `sonar-issues.md`; renamed in lockstep with `DEFAULT_OUTPUT_NAME`.)

### What the migration does

- Walks `<folder>/<category>/L*.json` files
- Groups by the `rule` field inside each JSON (more reliable than the trimmed folder name)
- Embeds `why.md` / `how.md` content inline under each rule section
- Marks closed-issue `Lunknown.json` files with `Lunknown` in the Line column (the closed-issue gotcha — see below)
- Uses a `local:` prefix on synthetic issue keys (when the JSON lacks a `key` field) so they're visually distinct from real API keys
- Original per-issue JSONs and why/how files are **left untouched** — migration is nondestructive

### Closed-issue gotcha

Closed issues have `line: null` in the SonarCloud API response. In 0.2.x local exports, these appeared as `Lunknown.json` files. In the migrated Markdown output, they render with `Lunknown` in the Line column. The `status` field is the source of truth — a closed/FIXED issue in a fresh export is stale, not a regression. Don't triage closed issues as new findings.

### `local:` prefix on keys

This happens when the 0.2.x export's `L{line}.json` files lack a `key` field (some older exports didn't include it). The `local:` prefix is intentional — it marks the key as synthetic so it's visually distinct from real API keys. Deep-link generation is suppressed for these keys (clicking would 404 on SonarCloud).

### Differences from 0.2.x

| Aspect | 0.2.x (`sonar-export` + `sonar-watch`) | 1.0.0 (`sie`) |
|---|---|---|
| **Binaries** | Two (`sonar-export`, `sonar-watch`) | One (`sie`) |
| **Install** | `uv tool install ".[markdown]"` (build step) | `curl ... -o ~/.local/bin/sie` (no build) |
| **Dependencies** | `requests`, `pyperclip`, optional `html2text` | Zero third-party deps (pure stdlib) |
| **Clipboard watcher** | `sonar-watch` polls clipboard every 1s | Removed — use `sie '<URL>'` directly |
| **Input forms** | Only `?open=<KEY>&id=<PROJECT>` (single-issue UI URL) | SonarCloud URL, GitHub URL, fuzzy `owner/repo[/branch]`, single-token shortcuts, no-arg |
| **Output** | Per-issue folder tree (`L{line}.json` + `why.md` + `how.md`) | Single Markdown file (`issues.md`) |
| **Quick triage** | Not supported | `--summary` flag (facets-only fetch) |
| **Token env var** | `BEARER_TOKEN` | `SONAR_API_KEY` (preferred) or `SONAR_TOKEN` (fallback) |
| **Local-folder migration** | Not supported | `sie -m [path]` (nondestructive) |
