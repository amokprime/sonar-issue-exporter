## Clean mode (`-c` / `--clean`)

Clean mode silently drops the Why/How rule-rationale subsections from the rendered Markdown — no placeholder, no warning. The `api/rules/show` fetch is skipped entirely (no point fetching content that will be dropped).

### Why

SonarCloud rule descriptions (the "why"/"how" content) are intellectual property of SonarSource SA. The README's AI disclosure notes: "Rule descriptions and educational content are the intellectual property of SonarSource SA. This tool does not bundle or redistribute SonarSource content."

When sharing a `sie` export with a chat agent (or pushing to a public repo), use `-c` to ensure no licensed content leaks.

### What's preserved

- **Instances table** (file, line, message, severity, rule key) — your own project's scan results, not licensed content.
- **Summary table** (severity/type counts, top rules) — also safe.
- **Focal Issue callout** — your project's issue metadata.
- **Header** — shows `Token: clean (why/how sections suppressed)` instead of present/absent.

Only the rule rationale sections (fetched from `api/rules/show`) are suppressed.

### Usage

```sh
sie -c amokprime/linebyline    # clean export — issue data only, no SonarSource content
sie -c amokprime/linebyline ~/report.md   # custom output path
```

### Verified behavior

- **With `-c`**: 0 Why sections, 0 How sections, but the Instances tables (one per rule) are intact.
- **Without `-c`** (token absent): Why/How sections render with placeholder text pointing to `SONAR_API_KEY`.
- **Without `-c`** (token present): Why/How sections render the full rule rationale fetched from `api/rules/show`.

Clean mode is independent of token presence — it suppresses the sections regardless of whether a token is available. This lets you produce a clean export even when you have a token, for cases where you want to share the issue data without the licensed rationale.
