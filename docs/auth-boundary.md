## Auth boundary

`sie`'s auth boundary mirrors the SonarCloud API's actual behavior (verified Sep 2026):

| What | Auth required? |
|---|---|
| Issue enumeration (`api/issues/search`) | No (for public projects) |
| Facets (`api/issues/search?facets=...`) | No |
| Pagination (`&p=N&ps=500`) | No |
| Rule rationale (`api/rules/show`) | Yes — needs token + organization |
| Single-issue lookup (`?issues=<KEY>`) | Yes — returns 0 results without auth |

### What works without a token

For public projects, you can skip the token entirely — `sie` runs in "public-project mode":

- `--summary` works fully (facets are unauthenticated) — quick triage, no file written
- Full export works for issue list + instances table — the core scan data
- GitHub URL → SonarCloud API URL conversion works (it's a pure URL transform)
- Local-folder migration works (no API calls — reads from disk)

### What's gated behind a token

- **Why/How rule rationale** — fetched via `api/rules/show`, which requires auth + the `organization` query param. Without a token, these sections render placeholders pointing to `SONAR_API_KEY`.
- **Single-issue lookup by key** — `?issues=<KEY>` on `api/issues/search` returns 0 results without auth (not an error — just an empty result that's easy to misread as "issue doesn't exist"). `sie` works around this for the Focal Issue feature by falling back to fetching the whole project's OPEN issues and filtering client-side.

### Token env vars

`sie` checks `SONAR_API_KEY` first (preferred), then `SONAR_TOKEN` (SonarQube convention fallback). No file-based config — keys must be in the shell environment.

If both env vars are unset/empty, `sie` reports "Token: absent" in the export header. Issue enumeration still works for public projects — only the why/how content is gated.

For token detection issues (KWallet, fish shell, "absent despite being set"), see [troubleshooting-token.md](troubleshooting-token.md).
