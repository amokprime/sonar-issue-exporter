## Output paths & positional disambiguation

### Output path priority

When no explicit output path is given, `sie` resolves the default output directory in this order:

1. **`scratch/`** if cwd (current working directory) is a git-tracked project root and `scratch/` exists → `scratch/issues.md`
2. **cwd** if cwd is a git root without `scratch/` → `./issues.md`
3. **cwd** if inside a git project but not at root → `./issues.md` (e.g. from `archive/0.2.0/`)
4. **`~/Downloads/`** (last resort) if not in a git project → `~/Downloads/issues.md`

All modes auto-increment: `issues.md` → `issues1.md` → `issues2.md`. (v1.1.0: renamed from `sonar-issues.md` since the file may contain CodeQL alerts, SonarCloud issues, or both.)

For `sie -m` (migration), the output defaults to alongside the issues folder (`<folder_parent>/issues.md`), not the git-aware path — the migration output belongs next to the input.

---

### Positional disambiguation

`sie` has two positionals: `[url_or_path] [output_path]`. To avoid ambiguity between "this is the output path" and "this is the migration input folder", local-path migration is gated behind the `-m` flag:

| Invocation | Resolves to |
|---|---|
| `sie` | input=main of cwd → `scratch/issues.md` (or cwd, or `~/Downloads`) |
| `sie amokprime/linebyline` | input=fuzzy → default output path |
| `sie amokprime/linebyline ~/r.md` | input=fuzzy → `~/r.md` |
| `sie /tmp/out.md` | input=main of cwd → `/tmp/out.md` (path-like positional = output) |
| `sie -m /path/to/issues` | migration → `<input_parent>/issues.md` |
| `sie -m /path/to/issues ~/r.md` | migration → `~/r.md` |
| `sie -m` | auto-discover `issues/` in cwd or cwd itself |
| `sie /path /tmp/out.md` (no -m) | **ambiguous error** with hints to use `-m` |

The rule: paths starting with `/`, `~/`, `./`, or `../` (or a Windows drive letter) are interpreted as the **output path** (with input defaulting to main of cwd's repo), unless `-m` is set. This means `sie ~/my-report.md` from project root does the right thing — fetches main-branch issues and writes to `~/my-report.md` — without needing `-i`/`-o` flags.

---

### Troubleshooting positional errors

#### `sie <path> <path>` errors with "ambiguous positionals"
You passed two positionals where the first looks like a local path. `sie` can't tell if the first positional is the migration input or if it's the input URL/fuzzy that happens to look path-ish.

- If you want to migrate: `sie -m <path1> <path2>` (path1 = migration folder, path2 = output)
- If you want to fetch issues with a custom output: pass a URL or fuzzy input as the first positional, e.g. `sie amokprime/linebyline <output>`

#### `sie <path>` (single path-like positional) writes to default output dir instead of migrating
Without `-m`, a single path-like positional is treated as the **output path** (with input defaulting to main of cwd's repo), not as a migration input.

- To migrate a local folder, use `sie -m <path>` (or just `sie -m` for auto-discovery).
