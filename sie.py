#!/usr/bin/env python3
"""sie — sonar-issue-exporter (v1.1.0).

A self-contained Python 3.10+ script that fetches SonarCloud issues and
GitHub code-scanning alerts (CodeQL etc.) and renders them into a single
Markdown file. Replaces the previous ``sonar-export`` + ``sonar-watch``
two-tool split (0.2.x). See README.md for the full input-forms reference,
disambiguation rules, and examples.

Usage:
    sie -h                 # short usage
    sie -v                 # version
    sie -s [INPUT]         # cheap triage -> stdout (no file written)
    sie [INPUT] [OUTPUT]   # full export -> Markdown
    sie -m [FOLDER] [OUTPUT]  # migrate a 0.2.x issues folder

Quick examples:
    sie                                    # main of CWD -> scratch/ or cwd
    sie amokprime/linebyline               # fuzzy input
    sie https://github.com/owner/repo/pull/11
    sie -s pr                              # triage most recent PR (via gh)
    sie -m                                 # auto-discover issues/ folder
    sie -m /path/to/issues                 # migrate explicit folder

See README.md for the full input forms, positional disambiguation, and
repo discovery rules.

Output path priority (non-migration): scratch/ if at git root, else cwd if
in a git project, else ~/Downloads (last resort). Auto-incrementing:
issues.md -> issues1.md -> issues2.md.

v1.1.0 behavior: ``sie``, ``sie staging``, and ``sie pr`` auto-discover
open repo-wide GitHub code-scanning alerts (CodeQL etc.) alongside the
branch-scoped SonarCloud issues. The two sources are rendered into a
single ``issues.md`` with separate sections per source. SonarCloud
issues that also appear as code-scanning alerts (pushed by the
SonarCloud GitHub Action) are deduped — the SonarCloud version wins.
If ``gh`` isn't available, the CodeQL capability is silently dropped.

Auth: issue enumeration and facets work unauthenticated for public
SonarCloud projects. Rule rationale (``api/rules/show``) requires a
token from the ``SONAR_API_KEY`` environment variable (or ``SONAR_TOKEN``
as fallback). CodeQL alerts require the GitHub CLI (``gh``) with
``gh auth login`` (and the ``security_events`` scope).

Exit codes: 0 on success, 1 on usage/write errors, 2 on API/transport
errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.1.0"
USER_AGENT = f"sie/{VERSION}"
SONARCLOUD_BASE = "https://sonarcloud.io"
GITHUB_BASE = "https://github.com"
# v1.1.0: renamed from "sonar-issues.md" — the file may contain
# SonarCloud issues, CodeQL alerts, or both (the new merged mode), so
# the name is source-agnostic. The migration safety check in
# _discover_migrate_folder also looks for this name.
DEFAULT_OUTPUT_NAME = "issues.md"
LAST_RESORT_OUTPUT_DIR = Path.home() / "Downloads"
SCRATCH_DIR_NAME = "scratch"
ISSUES_DIR_NAME = "issues"
PAGE_SIZE = 500  # SonarCloud max page size
REQUEST_TIMEOUT = 30.0

# Severity display order (worst first). Issues with unknown severity sort last.
SEVERITY_ORDER: dict[str, int] = {
    "BLOCKER": 0, "CRITICAL": 1, "MAJOR": 2, "MINOR": 3, "INFO": 4,
}

# Matches L1234.json and L1234_2.json (case-insensitive). The legacy export
# also emits Lunknown.json for closed issues (line: null) — the optional
# "unknown" token below catches that case.
ISSUE_FILE_RE = re.compile(
    r"^L(?:unknown|(\d+))(?:_\d+)?\.json$", re.IGNORECASE,
)

# Field ordering for the embedded per-issue JSON: identity -> location ->
# description -> classification -> multi-line evidence arrays.
# Rationale (per archive/0.1.2/0.1.2.md): one-liners first so reviewers get
# a full picture at a glance; arrays last so they don't push quick-scan
# info off screen.
KEEP_FIELDS = (
    "rule",
    "component",
    "line",
    "textRange",
    "message",
    "severity",
    "type",
    "cleanCodeAttribute",
    "cleanCodeAttributeCategory",
    "impacts",
    "flows",
)

# Crude HTML tag stripper for the SonarCloud rule htmlDesc field. We don't
# need full fidelity — the rule descriptions are simple HTML (p, code, a,
# strong, br). Anything more complex falls through unmodified.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# GitHub URL/SSH forms. Accepts:
#   - https://github.com/owner/repo[.git][/anything]
#   - git+https://github.com/owner/repo[.git]
#   - ssh://git@github.com/owner/repo[.git]
#   - git@github.com:owner/repo[.git]
GITHUB_HTTPS_RE = re.compile(
    r"^(?:git\+)?https?://(?:www\.)?github\.com/"
    r"([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$"
)
GITHUB_SSH_RE = re.compile(
    r"^(?:ssh://)?git@github\.com:([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$"
)

# Fuzzy owner/repo[/branch] input form. Owner and repo parts allow
# alphanumerics, hyphens, dots, and underscores; branch allows the same
# plus slashes for branch names with paths (rare but possible).
FUZZY_OWNER_REPO_RE = re.compile(
    r"^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)(?:/(.+))?$"
)


# ---------------------------------------------------------------------------
# Configuration: API key from environment variables
# ---------------------------------------------------------------------------

def get_token() -> str | None:
    """Return the SonarCloud API key from environment variables.

    No file-based config (no ``.env`` reading) — keys must be in the shell
    environment. The recommended setup is to export the key in your shell
    rc (e.g. ``~/.config/fish/config.fish``):
        set -gx SONAR_API_KEY (kwallet-query -f ksshaskpass -r Sonar kdewallet | string trim)

    ``SONAR_API_KEY`` is preferred (matches the user's setup). ``SONAR_TOKEN``
    is accepted as a fallback for users following the SonarQube convention.

    Returns the token string if set and non-empty. Returns ``None`` if the
    var is unset OR set to an empty string (treated as "absent" — this
    catches the case where ``kwallet-query`` returned empty because KWallet
    was locked at shell-startup time).
    """
    val = os.environ.get("SONAR_API_KEY") or os.environ.get("SONAR_TOKEN")
    return val if val else None


def _debug_env() -> int:
    """Print token env var status for debugging. Returns 0 always.

    Used by ``sie --debug-env`` to diagnose why ``sie`` reports "Token:
    absent" when the user believes the var is set. Checks each candidate
    env var and reports: not set / set but empty / set with N chars.
    """
    print("sie token env var diagnostic:")
    for var in ("SONAR_API_KEY", "SONAR_TOKEN"):
        val = os.environ.get(var)
        if val is None:
            print(f"  {var}: not set")
        elif val == "":
            print(f"  {var}: set but EMPTY (kwallet-query may have returned '')")
        else:
            print(f"  {var}: set, {len(val)} chars, starts with {val[:4]}…")
    token = get_token()
    if token:
        print(f"\nget_token() returns: {len(token)}-char token (will be used)")
    else:
        print("\nget_token() returns: None (token absent)")
        print("\nPossible causes:")
        print("  1. Env var not exported (fish: `set -gx`, not `set -g`)")
        print("  2. kwallet-query returned empty (KWallet locked at shell startup)")
        print("  3. sie invoked from a context that doesn't inherit the shell env")
        print("     (e.g. desktop launcher, cron, non-login shell)")
        print("  4. Universal var set in one fish session, not yet loaded in this one")
    return 0


# ---------------------------------------------------------------------------
# URL parsing & normalization
# ---------------------------------------------------------------------------

def looks_like_url(s: str) -> bool:
    """Heuristic: does this string look like an HTTP(S) URL?"""
    return s.startswith(("http://", "https://"))


def looks_like_local_path(s: str) -> bool:
    """Heuristic: does this string look like a local filesystem path?

    Covers absolute paths (``/...``), home-relative (``~/...``), relative
    (``./...``, ``../...``), and Windows-style (``.\\...``, ``C:\\...``).
    """
    return bool(
        s.startswith(("/", "~/", "./", "../", ".\\", "..\\"))
        or re.match(r"^[A-Za-z]:[\\/]", s)
    )


def parse_url_input(raw: str) -> dict:
    """Parse a SonarCloud URL (API or UI) into a normalized descriptor.

    Returns a dict with keys:
      - ``api_url``: the API URL to fetch (always ``/api/issues/search``)
      - ``project``: the project key (for display + deep links)
      - ``scope``: ``"main"`` | ``"branch:<NAME>"`` | ``"pr:<N>"`` (display)
      - ``focal_key``: an issue key if the URL had ``?open=<KEY>``, else None

    For UI URLs (``/project/issues?...``), all extra query params
    (``sinceLeakPeriod``, ``rules``, ``tags``, etc.) are passed through to
    the API URL. Only ``id``, ``open``, ``pullRequest``, ``branch`` are
    consumed for descriptor fields; the rest are preserved verbatim.

    Raises ``ValueError`` on unparseable URLs (non-sonarcloud host,
    unrecognized path, missing required query params).
    """
    parsed = urllib.parse.urlparse(raw)
    if parsed.netloc not in ("sonarcloud.io", "www.sonarcloud.io"):
        raise ValueError(
            f"Not a sonarcloud.io URL: {raw!r} "
            "(sie only handles sonarcloud.io URLs)"
        )

    # parse_qs returns lists; we flatten single-element lists for convenience.
    qs_lists = urllib.parse.parse_qs(parsed.query)
    qs = {k: v[0] if len(v) == 1 else v for k, v in qs_lists.items()}

    if parsed.path.startswith("/api/issues/search"):
        # API URL — pass through, but normalize a few things:
        # - ensure issueStatuses present (default OPEN, per the SKILL.md
        #   convention of triaging OPEN findings)
        # - force ps=500 (max page size) for efficient pagination
        params = dict(qs)
        params.setdefault("issueStatuses", "OPEN")
        params["ps"] = str(PAGE_SIZE)
        project = params.get("componentKeys", "")
        scope = _scope_from_params(params)
        focal_key = qs.get("issues") if isinstance(qs.get("issues"), str) else None
        api_url = _build_api_url(params)
        return {
            "api_url": api_url,
            "project": project,
            "scope": scope,
            "focal_key": focal_key,
        }

    if parsed.path.startswith("/project/issues"):
        # UI URL — convert to API URL.
        if "id" not in qs:
            raise ValueError(
                f"SonarCloud UI URL missing ?id=<PROJECT> param: {raw!r}"
            )
        project = qs["id"]
        # Start with all the UI URL's params (preserves sinceLeakPeriod,
        # rules, tags, etc.), then map UI param names -> API param names
        # and set defaults.
        params = dict(qs)
        # UI uses `id`; API uses `componentKeys`. Rename + remove the UI name.
        params["componentKeys"] = project
        params.pop("id", None)
        # `open` is a UI-only param (single-issue deep link) — not a valid
        # API param, so extract it for the focal_key and remove from params.
        focal_key = params.pop("open", None)
        # Default to OPEN if not specified; preserve user's value if present.
        params.setdefault("issueStatuses", "OPEN")
        params["ps"] = str(PAGE_SIZE)
        scope = _scope_from_params(params)
        api_url = _build_api_url(params)
        return {
            "api_url": api_url,
            "project": project,
            "scope": scope,
            "focal_key": focal_key,
        }

    raise ValueError(
        f"Unrecognized SonarCloud URL path: {parsed.path!r}. "
        "Expected /api/issues/search or /project/issues."
    )


def _scope_from_params(params: dict) -> str:
    if "pullRequest" in params:
        return f"pr:{params['pullRequest']}"
    if "branch" in params:
        return f"branch:{params['branch']}"
    return "main"


def _build_api_url(params: dict) -> str:
    """Build a /api/issues/search URL from a params dict.

    ``safe=":,"`` keeps the colon in rule keys (``javascript:S2681``) and
    the comma in multi-value ``issueStatuses=OPEN,CONFIRMED`` unescaped.
    """
    return (
        f"{SONARCLOUD_BASE}/api/issues/search?"
        + urllib.parse.urlencode(params, safe=":,")
    )


# ---------------------------------------------------------------------------
# SonarCloud API client (urllib; Bearer auth)
# ---------------------------------------------------------------------------

def _api_get(url: str, token: str | None, timeout: float = REQUEST_TIMEOUT) -> dict:
    """GET a SonarCloud API URL and return parsed JSON.

    Uses Bearer auth (matches export_sonar_issue.py 0.2.x contract).
    Raises ``RuntimeError`` on HTTP or network errors (with the URL + body
    snippet for diagnostics).
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(
            f"HTTP {e.code} {e.reason} from {url}\nBody: {body}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e}") from e


def _with_page_param(api_url: str, page: int) -> str:
    """Return ``api_url`` with ``&p=<page>`` set (replacing any existing)."""
    parsed = urllib.parse.urlparse(api_url)
    qs_lists = urllib.parse.parse_qs(parsed.query)
    qs_lists["p"] = [str(page)]
    qs = {k: v[0] if len(v) == 1 else ",".join(v) for k, v in qs_lists.items()}
    new_query = urllib.parse.urlencode(qs, safe=":,")
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def fetch_issues(api_url: str, token: str | None) -> tuple[list[dict], dict]:
    """Fetch all issues from an API URL, paginating as needed.

    Returns ``(issues, facets)``. ``facets`` is a dict of
    ``{property: [{val, count}, ...]}`` — empty if the URL had no
    ``facets=`` param. Prints page progress to stderr.
    """
    page_url = _with_page_param(api_url, 1)
    data = _api_get(page_url, token)
    issues = list(data.get("issues", []))
    total = int(data.get("total", 0))
    facets_raw = data.get("facets", []) or []
    facets = {f["property"]: f.get("values", []) for f in facets_raw}

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if pages > 1:
        print(f"  page 1/{pages} ({len(issues)}/{total})", file=sys.stderr)
        for p in range(2, pages + 1):
            page_url = _with_page_param(api_url, p)
            data = _api_get(page_url, token)
            issues.extend(data.get("issues", []))
            print(f"  page {p}/{pages} ({len(issues)}/{total})", file=sys.stderr)

    return issues, facets


def fetch_rule(rule_key: str, organization: str, token: str | None) -> dict | None:
    """Fetch rule metadata (why/how content). Requires auth + organization.

    Returns the rule dict from ``api/rules/show``, or ``None`` if the
    request fails (e.g. no token, HTTP 400, network error).
    """
    if not token:
        return None
    params = {"key": rule_key}
    if organization:
        params["organization"] = organization
    url = (
        f"{SONARCLOUD_BASE}/api/rules/show?"
        + urllib.parse.urlencode(params)
    )
    try:
        data = _api_get(url, token)
        return data.get("rule") or None
    except RuntimeError as e:
        print(
            f"  warning: rule fetch failed for {rule_key}: {e}",
            file=sys.stderr,
        )
        return None


def extract_rule_descriptions(rule: dict) -> tuple[str, str]:
    """Extract the 'why' and 'how' HTML content from a rule dict.

    Mirrors export_sonar_issue.py's extract_rule_descriptions(). Returns
    ``(why_html, how_html)``.

    SonarCloud's newer rule format uses ``descriptionSections`` with keys
    like ``introduction``, ``root_cause``, ``how_to_fix``. Older rules
    only have ``htmlDesc`` (a single blob). We try the structured form
    first, falling back to ``htmlDesc`` / ``mdDesc``.
    """
    sections = {
        s["key"]: s.get("content", "")
        for s in rule.get("descriptionSections", [])
    }

    if sections:
        intro = sections.get("introduction", "")
        root = sections.get("root_cause", "")
        why_html = f"{intro}\n\n{root}".strip()
        how_html = sections.get("how_to_fix", "")
        if not why_html:
            why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
    else:
        why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
        how_html = ""

    return why_html, how_html


def _strip_leading_heading(text: str) -> str:
    """Strip a leading Markdown heading line if present.

    Local-export ``why.md`` / ``how.md`` files typically start with a
    heading like ``# Why is this an issue?`` that duplicates the
    ``### Why`` subsection header in our rendered Markdown. Strip it so
    the rendered output doesn't have two consecutive headings.
    """
    if not text:
        return text
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        # Drop the heading line, plus any blank line immediately after.
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def _strip_html(html: str) -> str:
    """Crude HTML -> text: strip tags, collapse whitespace, decode common
    entities. Adequate for SonarCloud rule descriptions (simple HTML:
    p, code, a, strong, br). Mirrors export_sonar_issue.py's fallback path.
    """
    if not html:
        return ""
    # Decode common entities first (before tag stripping, so encoded
    # < inside <code> doesn't get re-stripped).
    text = (
        html.replace("<", "<")
        .replace(">", ">")
        .replace("&", "&")
        .replace("&nbsp;", " ")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    # Convert <br> and block-level closers to newlines for readability.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|li|h[1-6])>", "\n\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    # Restore the paragraph breaks we inserted (collapsed to single spaces).
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def fetch_rule_md(
    rule_key: str, organization: str, token: str | None,
) -> tuple[str, str]:
    """Fetch a rule and return ``(why_md, how_md)``.

    Returns empty strings on failure (no token, fetch error). The caller
    decides how to render the missing-content case.
    """
    rule = fetch_rule(rule_key, organization, token)
    if not rule:
        return "", ""
    why_html, how_html = extract_rule_descriptions(rule)
    return _strip_html(why_html), _strip_html(how_html)


# ---------------------------------------------------------------------------
# GitHub code-scanning alerts (via `gh api` — requires GitHub CLI auth)
# ---------------------------------------------------------------------------

def fetch_code_scanning_alert(
    owner: str, repo: str, alert_num: int,
) -> dict:
    """Fetch a single GitHub code-scanning alert via `gh api`.

    Mirrors the ``sie pr`` pattern: requires the GitHub CLI (``gh``) with
    ``gh auth login`` done. The repo must be public (or the user must have
    access via their ``gh`` token).

    Returns the raw alert JSON (per the GitHub code-scanning alerts API).
    Raises ``RuntimeError`` if ``gh`` isn't installed, the API call fails,
    or the response isn't valid JSON.
    """
    if not shutil.which("gh"):
        raise RuntimeError(
            "GitHub code-scanning alerts require the GitHub CLI (`gh`). "
            "Install from https://cli.github.com, then `gh auth login`. "
            "For SonarCloud issues, use the SonarCloud URL form instead."
        )
    api_path = f"repos/{owner}/{repo}/code-scanning/alerts/{alert_num}"
    try:
        proc = subprocess.run(
            ["gh", "api", api_path],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise RuntimeError(f"`gh api {api_path}` invocation failed: {e}") from e
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            f"`gh api {api_path}` failed (exit {proc.returncode}): {stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"`gh api {api_path}` returned non-JSON output: {e}"
        ) from e


def fetch_open_code_scanning_alerts(owner: str, repo: str) -> list[dict]:
    """Fetch all open GitHub code-scanning alerts for a repo via ``gh api``.

    Uses ``--paginate`` to follow Link headers, collecting every open
    alert across all pages in one call. Returns ``[]`` silently if ``gh``
    is not installed, not authenticated, or the API call fails for any
    other reason (rate limit, network, repo not found, etc.).

    The silent-drop behavior is intentional: the v1.1.0 auto-discovery
    contract is "best-effort CodeQL alongside SonarCloud" — if the
    CodeQL capability isn't available, the SonarCloud fetch still
    completes and produces a SonarCloud-only report. Callers should
    treat ``[]`` as "no CodeQL alerts" without distinguishing the cause.

    Returns the list of alert JSON dicts (per the GitHub code-scanning
    alerts API shape — each has ``number``, ``state``, ``rule``,
    ``tool``, ``most_recent_instance``, etc.).
    """
    if not shutil.which("gh"):
        return []
    api_path = (
        f"repos/{owner}/{repo}/code-scanning/alerts"
        f"?state=open&per_page=100&sort=created&direction=desc"
    )
    try:
        proc = subprocess.run(
            ["gh", "api", "--paginate", api_path],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def _is_sonar_pushed_alert(alert: dict) -> bool:
    """Check if a code-scanning alert was pushed by SonarCloud.

    SonarCloud's GitHub Action pushes its findings to the code-scanning
    view via SARIF upload. The ``tool.name`` field in the alert reflects
    the SARIF ``runs[].tool.driver.name`` — for SonarCloud pushes this
    is ``"SonarCloud"`` (or ``"SonarQube"`` for self-hosted SonarQube
    instances configured the same way). Native CodeQL alerts have
    ``tool.name == "CodeQL"``.

    These SonarCloud-pushed alerts are duplicates of what the SonarCloud
    API already returns in the same ``sie`` run — drop them to avoid
    showing the same finding twice. The matching is on the substring
    ``"sonar"`` (case-insensitive) so it catches both "SonarCloud" and
    "SonarQube" without listing each variant.
    """
    tool = alert.get("tool", {})
    name = (tool.get("name") or "").lower()
    return "sonar" in name


def _code_scanning_alerts_to_issues(
    alerts: list[dict],
) -> tuple[list[dict], dict[str, dict]]:
    """Convert a list of GitHub code-scanning alerts to sie issue dicts.

    Returns ``(issues, rules)`` where ``issues`` is the list of converted
    issue dicts (one per alert) and ``rules`` is the metadata dict keyed
    by rule ID with ``{"why", "how"}`` values (the ``why`` is the alert's
    ``rule.help`` markdown; ``how`` is empty — the GitHub API doesn't
    separate fix guidance from explanation).

    The first alert seen for a given rule wins the metadata slot — later
    alerts for the same rule reuse the same metadata. This matches the
    SonarCloud path's behavior (one rule section per rule, multiple
    instances listed in its Instances table).
    """
    issues: list[dict] = []
    rules: dict[str, dict] = {}
    for alert in alerts:
        issue = _code_scanning_alert_to_issue(alert)
        issues.append(issue)
        rule_key = issue["rule"]
        if rule_key not in rules:
            rules[rule_key] = _code_scanning_rule_to_meta(alert)
    return issues, rules


def _fetch_code_scanning_for_project(
    project: str,
) -> tuple[list[dict], dict[str, dict]]:
    """Fetch repo-wide open CodeQL alerts for a project, deduped.

    Splits the project key ``<owner>_<repo>`` back into owner/repo,
    fetches all open code-scanning alerts via ``gh api``, and drops
    SonarCloud-pushed alerts (they're already in the SonarCloud fetch).
    Returns ``(issues, rules)`` — both empty if ``gh`` is unavailable
    or the project key doesn't split into owner/repo.

    This is the v1.1.0 auto-discovery entry point called by
    ``export_url`` after the SonarCloud fetch completes. The silent-drop
    semantics (no warnings, no errors) match the user spec: "If ``gh``
    login isn't available, just drop this capability silently."
    """
    owner, sep, repo = project.partition("_")
    if not sep or not owner or not repo:
        return [], {}
    alerts = fetch_open_code_scanning_alerts(owner, repo)
    if not alerts:
        return [], {}
    native_alerts = [a for a in alerts if not _is_sonar_pushed_alert(a)]
    if not native_alerts:
        return [], {}
    return _code_scanning_alerts_to_issues(native_alerts)


def _code_scanning_alert_to_issue(alert: dict) -> dict:
    """Convert a GitHub code-scanning alert JSON to a sie issue dict.

    Maps the alert's fields to the ``KEEP_FIELDS`` shape so
    ``render_markdown`` can render it without branching on the source.
    The ``key`` is a synthetic ``codeql:<alert_number>`` so it's visually
    distinct from SonarCloud issue keys.
    """
    rule = alert.get("rule", {})
    instance = alert.get("most_recent_instance", {})
    location = instance.get("location", {})
    return {
        "rule": rule.get("id", "?"),
        "component": location.get("path", "?"),
        "line": location.get("start_line"),
        "textRange": {
            "startLine": location.get("start_line"),
            "endLine": location.get("end_line"),
            "startOffset": location.get("start_column"),
            "endOffset": location.get("end_column"),
        },
        "message": instance.get("message", {}).get("text", ""),
        "severity": rule.get("severity", "warning").upper(),
        "type": "CODE_SMELL",
        "cleanCodeAttribute": "FOCUSED",
        "cleanCodeAttributeCategory": "ADAPTABLE",
        "impacts": [],
        "flows": [],
        "status": alert.get("state", "open").upper(),
        "key": f"codeql:{alert.get('number', '?')}",
    }


def _code_scanning_rule_to_meta(alert: dict) -> dict:
    """Extract rule metadata (why/how) from a code-scanning alert.

    The alert's ``rule.help`` field is markdown — use it as the ``why``
    content. There's no separate "how to fix" section in the GitHub API;
    the help text usually contains both the explanation and remediation.
    """
    rule = alert.get("rule", {})
    help_text = rule.get("help", "")
    return {"why": help_text, "how": ""}


def render_code_scanning_markdown(
    *, source: str, owner: str, repo: str, alert: dict,
) -> str:
    """Render a single GitHub code-scanning alert as a sie-style Markdown report.

    Reuses ``render_markdown`` by converting the alert to the issue-dict
    shape. The report has one rule section with one instance (the alert
    location), plus the rule's help text as the Why section.
    """
    issue = _code_scanning_alert_to_issue(alert)
    rule_meta = _code_scanning_rule_to_meta(alert)
    project = f"{owner}_{repo}"
    return render_markdown(
        source=source,
        project=project,
        scope="code-scanning",
        issues=[issue],
        facets={},
        rules={issue["rule"]: rule_meta},
        token_present=True,
        focal_key=issue["key"],
        is_local_migration=False,
        clean=False,
    )


# ---------------------------------------------------------------------------
# Local-folder parser (migration from existing 0.2.x per-issue exports)
# ---------------------------------------------------------------------------

def _parse_issue_from_json(json_path: Path, match: re.Match) -> dict | None:
    """Parse a single ``L*.json`` file into a cleaned issue dict.

    Returns ``None`` on JSON decode failure (after printing a warning) so
    the caller can skip the file without a nested try/except.

    Normalizes the field set to ``KEEP_FIELDS`` order when all are present
    (the 0.2.x export shape), else passes the raw dict through. Derives
    ``line`` from the filename when missing (the ``L<n>`` or ``Lunknown``
    convention), defaults ``status`` to ``OPEN``, and prefers the real
    ``key`` from disk when present (falling back to a ``local:``-prefixed
    synthetic key so the Markdown table has something to display).
    """
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"  warning: skipping malformed {json_path}: {e}",
            file=sys.stderr,
        )
        return None

    # The 0.2.x export writes a cleaned subset (KEEP_FIELDS only).
    # Some older exports may have different field sets — normalize
    # to KEEP_FIELDS order if all are present, else pass through.
    if all(k in data for k in KEEP_FIELDS):
        clean = {k: data[k] for k in KEEP_FIELDS}
    else:
        clean = dict(data)

    # Preserve the real `key` field if the JSON had one. Older 0.2.x
    # exports may not include it; in that case synthesize one with a
    # `local:` prefix so it's visually distinct from real API keys.
    #
    # Note: `key` is intentionally NOT in KEEP_FIELDS (which controls
    # the displayed field order for issues fetched fresh from the
    # API, where `key` always exists). For local migration we restore
    # it after the KEEP_FIELDS filter so the real key from disk wins.
    if "line" not in clean:
        line_str = match.group(1)
        clean["line"] = int(line_str) if line_str else None
    clean.setdefault("status", "OPEN")
    real_key = data.get("key")
    if real_key:
        clean["key"] = real_key
    elif "key" not in clean or not clean.get("key"):
        clean["key"] = _derive_key_from_path(json_path)
    return clean


def _register_rule_metadata(
    rules: dict[str, dict], rule_key: str, why_text: str, how_text: str,
) -> None:
    """Register why/how text for a rule, backfilling empty prior entries.

    A rule's first-seen category folder might have had empty ``why.md`` /
    ``how.md``; a later sibling category folder for the same rule may
    fill them in. This backfills the prior entry rather than overwriting.
    """
    if rule_key not in rules:
        rules[rule_key] = {"why": why_text, "how": how_text}
        return
    if not rules[rule_key]["why"] and why_text:
        rules[rule_key]["why"] = why_text
    if not rules[rule_key]["how"] and how_text:
        rules[rule_key]["how"] = how_text


def _process_category_dir(
    category_dir: Path, issues: list[dict], rules: dict[str, dict],
) -> None:
    """Process one category subfolder: read why/how, parse each L*.json, register rules.

    Extracted from ``parse_local_export`` to keep cognitive complexity under
    the S3776 threshold — the nested for>for>if structure was the complexity
    sink; this helper flattens it to a single for>if chain.
    """
    why_text = ""
    how_text = ""
    why_path = category_dir / "why.md"
    how_path = category_dir / "how.md"
    if why_path.is_file():
        why_text = why_path.read_text(encoding="utf-8").strip()
    if how_path.is_file():
        how_text = how_path.read_text(encoding="utf-8").strip()

    for json_path in sorted(category_dir.iterdir()):
        m = ISSUE_FILE_RE.match(json_path.name)
        if not m:
            continue
        clean = _parse_issue_from_json(json_path, m)
        if clean is None:
            continue

        issues.append(clean)
        rule_key = clean.get("rule")
        if not rule_key:
            continue
        _register_rule_metadata(rules, rule_key, why_text, how_text)


def parse_local_export(folder: Path) -> tuple[list[dict], dict[str, dict]]:
    """Walk a local export folder and collect issues + rule metadata.

    Expected layout (per sonarqube-workflow-SKILL.md + 0.2.x
    export_sonar_issue.py)::

        <folder>/
          <category>/                  # one folder per rule category
            L1234.json                 # one per issue instance, named by line
            L1234_2.json               # second issue on the same line
            Lunknown.json              # closed issue (line: null in API)
            why.md                     # rule rationale (shared per rule)
            how.md                     # fix guidance (shared; absent on simple rules)

    The category folder name has ``_1``/``_2`` instance counters and
    complexity suffixes stripped upstream — we use the ``rule`` field
    inside each ``L*.json`` for grouping, which is more reliable than the
    folder name.

    Returns ``(issues, rules)`` where ``issues`` is a list of issue dicts
    (the cleaned subset, matching KEEP_FIELDS order) and ``rules`` is
    ``{rule_key: {"why": str, "how": str}}``.
    """
    issues: list[dict] = []
    rules: dict[str, dict] = {}

    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")

    for category_dir in sorted(folder.iterdir()):
        if not category_dir.is_dir():
            continue
        _process_category_dir(category_dir, issues, rules)

    return issues, rules


def _derive_key_from_path(p: Path) -> str:
    """Best-effort synthetic issue key for local exports that lack one.

    Falls back to the parent folder + filename, so the Markdown table has
    *something* to display in the Key column. Real API keys look like
    ``AaBprftR68fRE0gxBFjx``; we mark synthetic ones with a ``local:``
    prefix to make them visually distinct.
    """
    return f"local:{p.parent.name}/{p.stem}"


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """UTC timestamp formatted as ``YYYY-MM-DD HH:MM UTC``."""
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def _md_escape_cell(s: str) -> str:
    """Escape pipe and newline for Markdown table cells."""
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", "")


def _strip_component(component: str, project: str) -> str:
    """Strip the leading ``<project>:`` prefix from a component path."""
    prefix = f"{project}:"
    if component.startswith(prefix):
        return component[len(prefix):]
    return component


def _deep_link(issue_key: str, project: str) -> str:
    """Build the SonarCloud UI deep link for a single issue.

    Only produces a real SonarCloud link when ``issue_key`` doesn't have
    the ``local:`` synthetic prefix.
    """
    if issue_key.startswith("local:"):
        return ""
    return f"{SONARCLOUD_BASE}/project/issues?open={issue_key}&id={project}"


def _rule_anchor(rule_key: str) -> str:
    """GitHub-style anchor: lowercase, replace non-alphanumerics with hyphens."""
    s = rule_key.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _scope_display(scope: str) -> str:
    """Map a scope string to its display form for the report header."""
    if scope == "main":
        return "main"
    if scope.startswith("pr:"):
        return f"PR #{scope[3:]}"
    if scope.startswith("branch:"):
        return f"branch `{scope[7:]}`"
    if scope == "local-export":
        return "local export"
    if scope == "code-scanning":
        return "GitHub code-scanning"
    return scope


def _render_header(
    *, source: str, project: str, scope: str, issues: list[dict],
    token_present: bool, is_local_migration: bool, clean: bool,
) -> list[str]:
    """Render the top-of-report header (title, generated, source, total, token)."""
    out: list[str] = []
    title_project = project or "(unknown project)"
    distinct_rules = {i.get("rule") for i in issues if i.get("rule")}
    out.append(f"# SonarQube Issues — {title_project} ({_scope_display(scope)})")
    out.append("")
    out.append(f"Generated: {_now_iso()}")
    out.append(f"Source: `{source}`")
    out.append(
        f"Total: {len(issues)} issue(s) across {len(distinct_rules)} rule(s)"
    )
    if is_local_migration:
        out.append("")
        out.append("---")
        out.append("")
        return out
    if clean:
        out.append("Token: clean (why/how sections suppressed)")
    else:
        out.append(f"Token: {'present' if token_present else 'absent'}")
        if not token_present:
            out.append("")
            out.append(
                "> ⚠ **No token set** — why/how rule-rationale subsections "
                "render as placeholders. Set `SONAR_API_KEY` (or "
                "`SONAR_TOKEN`) in your environment to fetch rule "
                "rationale via `api/rules/show`.\n"
                ">\n"
                "> If you believe the var is set, run `sie -d` to diagnose "
                "(checks for not-set vs empty vs set-with-N-chars)."
            )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _render_focal_issue(
    focal_issue: dict, focal_key: str, project: str,
) -> list[str]:
    """Render the focal-issue callout block (only when ?open=<KEY> was in the URL)."""
    out: list[str] = []
    rule_key = focal_issue.get("rule", "")
    out.append("## ★ Focal Issue")
    out.append("")
    out.append(f"- **Key:** `{focal_key}`")
    out.append(f"- **Rule:** `{rule_key}`")
    comp = _strip_component(focal_issue.get("component", ""), project)
    line = focal_issue.get("line")
    out.append(f"- **File:** `{comp}:{line or 'unknown'}`")
    out.append(
        f"- **Severity:** {focal_issue.get('severity', '?')} · "
        f"**Type:** {focal_issue.get('type', '?')} · "
        f"**Status:** {focal_issue.get('status', '?')}"
    )
    msg = focal_issue.get("message", "")
    if msg:
        out.append(f"- **Message:** {msg}")
    out.append("")
    link = _deep_link(focal_key, project)
    if link:
        out.append(f"→ [Open in SonarCloud]({link})")
    if rule_key:
        out.append(
            f"→ See rule section: [`{rule_key}`](#{_rule_anchor(rule_key)})"
        )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _compute_facets(
    facets: dict, issues: list[dict],
) -> tuple[list, list, list]:
    """Return (sev_facet, type_facet, rule_facet).

    Use API facets when present; otherwise compute from the issue list
    (local-migration path, or when the API URL didn't request facets).
    """
    if facets:
        return (
            facets.get("severities", []),
            facets.get("types", []),
            facets.get("rules", []),
        )
    sev_facet = [
        {"val": k, "count": v}
        for k, v in Counter(i.get("severity", "?") for i in issues).most_common()
    ]
    type_facet = [
        {"val": k, "count": v}
        for k, v in Counter(i.get("type", "?") for i in issues).most_common()
    ]
    rule_facet = [
        {"val": k, "count": v}
        for k, v in Counter(i.get("rule", "?") for i in issues).most_common()
    ]
    return sev_facet, type_facet, rule_facet


def _render_summary_section(facets: dict, issues: list[dict]) -> list[str]:
    """Render the Summary section (severity/type table + top rules list)."""
    out: list[str] = []
    out.append("## Summary")
    out.append("")
    sev_facet, type_facet, rule_facet = _compute_facets(facets, issues)
    sev_ordered = sorted(
        sev_facet, key=lambda v: SEVERITY_ORDER.get(v.get("val", ""), 99)
    )
    type_ordered = sorted(type_facet, key=lambda v: -v.get("count", 0))
    out.append("| Severity   | Count |   | Type          | Count |")
    out.append("|------------|-------|---|---------------|-------|")
    for i in range(max(len(sev_ordered), len(type_ordered))):
        s = sev_ordered[i] if i < len(sev_ordered) else {"val": "", "count": ""}
        t = type_ordered[i] if i < len(type_ordered) else {"val": "", "count": ""}
        out.append(
            f"| {str(s.get('val', '')):<10} | {str(s.get('count', '')):<5} | "
            f" | {str(t.get('val', '')):<13} | {str(t.get('count', '')):<5} |"
        )
    out.append("")
    if rule_facet:
        top_rules = sorted(
            rule_facet,
            key=lambda v: (-v.get("count", 0), v.get("val", "")),
        )[:10]
        out.append("Top rules:")
        for r in top_rules:
            out.append(f"- `{r.get('val', '?')}` — {r.get('count', 0)}×")
        out.append("")
    out.append("---")
    out.append("")
    return out


def _render_why_section(
    rule_meta: dict, is_local_migration: bool, token_present: bool,
) -> list[str]:
    """Render the ### Why subsection for a rule.

    Branches on (a) whether ``why.md`` content was present, (b) whether
    this is a local-folder migration (no API fetch involved), (c) whether
    a token was available for the ``api/rules/show`` fetch.
    """
    out: list[str] = ["### Why"]
    why_text = _strip_leading_heading(rule_meta.get("why", ""))
    if why_text:
        out.append(why_text)
    elif is_local_migration:
        out.append("(no `why.md` content was present in the local export)")
    elif not token_present:
        out.append(
            "> ⚠ Set `SONAR_API_KEY` to fetch rule rationale (`why.md` "
            "content) via `api/rules/show`."
        )
    else:
        out.append("(rule rationale fetch returned no content for this rule)")
    out.append("")
    return out


def _render_how_section(
    rule_meta: dict, is_local_migration: bool, token_present: bool,
) -> list[str]:
    """Render the ### How to fix subsection for a rule.

    Mirrors ``_render_why_section`` with how-specific fallback text when
    SonarCloud's ``api/rules/show`` returns no separate fix guidance.
    """
    out: list[str] = ["### How to fix"]
    how_text = _strip_leading_heading(rule_meta.get("how", ""))
    if how_text:
        out.append(how_text)
    elif is_local_migration:
        out.append("(no `how.md` content was present in the local export)")
    elif not token_present:
        out.append(
            "> ⚠ Set `SONAR_API_KEY` to fetch fix guidance (`how.md` "
            "content) via `api/rules/show`."
        )
    else:
        out.append(
            "(SonarCloud's `api/rules/show` did not return separate "
            "fix guidance for this rule; see the rule's full "
            "description under **Why** above, or the rule page on "
            "SonarCloud.)"
        )
    out.append("")
    return out


def _render_instances_table(
    rule_issues_sorted: list[dict], project: str, focal_key: str | None,
) -> list[str]:
    """Render the ### Instances table for a rule + the deep-link footer if applicable."""
    out: list[str] = []
    out.append("### Instances")
    out.append("")
    out.append("| File | Line | Message | Key | Status |")
    out.append("|------|------|---------|-----|--------|")
    for i in rule_issues_sorted:
        comp = _strip_component(i.get("component", ""), project)
        line = i.get("line")
        line_str = f"L{line}" if line else "Lunknown"
        msg = _md_escape_cell(i.get("message", ""))
        key = i.get("key", "")
        status = i.get("status", "?")
        star = "★ " if focal_key and key == focal_key else ""
        out.append(
            f"| `{star}{comp}` | {line_str} | {msg} | `{key}` | {status} |"
        )
    out.append("")
    if project and any(
        i.get("key") and not i["key"].startswith("local:")
        for i in rule_issues_sorted
    ):
        out.append(
            f"Deep links: `{SONARCLOUD_BASE}/project/issues?open=<KEY>&id={project}`"
        )
        out.append("")
    return out


def _render_per_rule_section(
    rk: str, rule_issues: list[dict], rules: dict[str, dict],
    focal_key: str | None, project: str,
    is_local_migration: bool, token_present: bool, clean: bool,
) -> list[str]:
    """Render a single rule's section (header, classification, why, how, instances)."""
    out: list[str] = []
    rule_issues_sorted = sorted(
        rule_issues,
        key=lambda i: (i.get("component", ""), i.get("line") or 0),
    )
    rule_meta = rules.get(rk, {})
    rule_name = rule_meta.get("name", "") or rk

    out.append(f"## Rule: `{rk}` — {rule_name}")
    out.append("")

    sev = Counter(i.get("severity", "?") for i in rule_issues)
    typ = Counter(i.get("type", "?") for i in rule_issues)
    cca = Counter(i.get("cleanCodeAttribute", "?") for i in rule_issues)
    sev_str = ", ".join(f"{k}: {v}" for k, v in sev.most_common())
    typ_str = ", ".join(f"{k}: {v}" for k, v in typ.most_common())
    cca_str = (
        ", ".join(f"{k}: {v}" for k, v in cca.most_common() if k != "?")
        if any(k != "?" for k in cca)
        else ""
    )
    out.append(
        f"Severity: {sev_str} · Type: {typ_str}"
        + (f" · CleanCode: {cca_str}" if cca_str else "")
        + f" · {len(rule_issues)} instance(s)"
    )
    out.append("")

    # Why/How — silently dropped when clean=True (avoid pushing licensed
    # Sonar content). The Instances table below is safe (issue data is
    # the user's own project's scan results, not SonarSource content).
    if not clean:
        out.extend(_render_why_section(rule_meta, is_local_migration, token_present))
        out.extend(_render_how_section(rule_meta, is_local_migration, token_present))

    out.extend(_render_instances_table(rule_issues_sorted, project, focal_key))
    out.append("---")
    out.append("")
    return out


def _render_per_rule_sections(
    issues: list[dict], rules: dict[str, dict],
    focal_key: str | None, project: str,
    is_local_migration: bool, token_present: bool, clean: bool,
) -> list[str]:
    """Group issues by rule, sort by (worst severity, count, key), render each section."""
    out: list[str] = []
    issues_by_rule: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        issues_by_rule[issue.get("rule", "(unknown)")].append(issue)

    def rule_sort_key(rk: str) -> tuple:
        rule_issues = issues_by_rule[rk]
        worst_sev = min(
            (SEVERITY_ORDER.get(i.get("severity", ""), 99) for i in rule_issues),
            default=99,
        )
        return (worst_sev, -len(rule_issues), rk)

    for rk in sorted(issues_by_rule.keys(), key=rule_sort_key):
        out.extend(_render_per_rule_section(
            rk, issues_by_rule[rk], rules, focal_key, project,
            is_local_migration, token_present, clean,
        ))
    return out


def render_markdown(
    *,
    source: str,
    project: str,
    scope: str,
    issues: list[dict],
    facets: dict,
    rules: dict[str, dict],
    token_present: bool,
    focal_key: str | None,
    is_local_migration: bool = False,
    clean: bool = False,
) -> str:
    """Render the full single-file Markdown report.

    Args:
        source: the input URL or local path (for the header)
        project: project key (e.g. ``amokprime_linebyline``)
        scope: ``"main"`` | ``"branch:<X>"`` | ``"pr:<N>"`` |
            ``"local-export"`` (display only)
        issues: list of issue dicts from the API or local parser
        facets: dict of ``{facet_property: [{val, count}, ...]}``. Empty for
            local migration — the renderer computes counts from issues.
        rules: dict of ``{rule_key: {"why", "how"}}``
        token_present: whether a token was available (affects why/how
            placeholder rendering)
        focal_key: an issue key to highlight at the top (from URL ``?open=``)
        is_local_migration: True when rendering a local-folder migration
            (suppressed token-absent warning, since why/how came from disk)
        clean: True when ``-c``/``--clean`` was passed. Silently drops the
            Why and How subsections entirely (no placeholder, no warning)
            to avoid pushing possibly-licensed Sonar content to a chat.
            When clean is True, the header's Token line shows "clean"
            instead of present/absent, and the per-rule sections omit the
            Why/How headers and content completely.

    The report is assembled from section helpers, each rendering one part
    (header, focal-issue callout, summary table, per-rule sections).
    Extracted to keep this function's cognitive complexity under the
    S3776 threshold (15) — the per-rule rendering in particular has enough
    branching (why/how placeholders, clean-mode suppression, instance
    sorting) to warrant its own helper.
    """
    out: list[str] = []
    out.extend(_render_header(
        source=source, project=project, scope=scope, issues=issues,
        token_present=token_present, is_local_migration=is_local_migration,
        clean=clean,
    ))
    if focal_key:
        focal_issue = next(
            (i for i in issues if i.get("key") == focal_key), None
        )
        if focal_issue:
            out.extend(_render_focal_issue(focal_issue, focal_key, project))
    out.extend(_render_summary_section(facets, issues))
    out.extend(_render_per_rule_sections(
        issues, rules, focal_key, project,
        is_local_migration, token_present, clean,
    ))
    return "\n".join(out).rstrip() + "\n"


def _demote_headings(md: str, levels: int = 1) -> str:
    """Demote all Markdown ATX headings by ``levels`` (e.g. ``#`` → ``##``).

    A line is treated as a heading if it starts with ``#``. Adds ``levels``
    additional ``#`` characters to the start of each heading line. Used by
    ``render_combined_markdown`` to nest a single-source render (which
    uses ``#`` for the title, ``##`` for sections, ``###`` for
    subsections) under a parent ``## SonarCloud Issues`` or
    ``## CodeQL Alerts`` heading.

    Non-heading lines (including indented code blocks that start with
    spaces, and fenced code blocks whose ``#`` is inside the fence) are
    passed through unchanged. The renderer's output doesn't currently
    emit fenced code blocks, so the indented-only check is sufficient.
    """
    out_lines = []
    for line in md.split("\n"):
        if line.startswith("#"):
            out_lines.append("#" * levels + line)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _strip_project_header(md: str) -> str:
    """Strip the project-level header from a ``render_markdown`` output.

    The header is everything from the start through the first ``---``
    separator line (inclusive). What remains starts with the focal-issue
    callout (if any) or the ``## Summary`` section.

    Used by ``render_combined_markdown`` to extract just the body of a
    single-source render so it can be demoted and nested under a parent
    ``## <Source> Issues`` heading. The parent emits its own
    project-level header once.
    """
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return md


def _render_combined_header(
    *, source: str, project: str, scope: str,
    sonar_count: int, codeql_count: int,
    distinct_rules: int, token_present: bool, clean: bool,
) -> list[str]:
    """Render the project-level header for a combined Sonar+CodeQL report.

    Mirrors ``_render_header`` but the Total line shows source counts
    (SonarCloud + CodeQL) instead of a single count. Emits ``Token:``
    based on the SonarCloud token state — CodeQL alerts don't need a
    SonarCloud token (their rule help is bundled in the alert JSON).
    """
    out: list[str] = []
    title_project = project or "(unknown project)"
    total = sonar_count + codeql_count
    sources = (1 if sonar_count else 0) + (1 if codeql_count else 0)
    out.append(f"# Issues — {title_project} ({_scope_display(scope)})")
    out.append("")
    out.append(f"Generated: {_now_iso()}")
    out.append(f"Source: `{source}`")
    out.append(
        f"Total: {total} issue(s) across {sources} source(s), "
        f"{distinct_rules} rule(s)"
        f"  (SonarCloud: {sonar_count}, CodeQL: {codeql_count})"
    )
    if clean:
        out.append("Token: clean (why/how sections suppressed)")
    else:
        out.append(f"Token: {'present' if token_present else 'absent'}")
        if not token_present:
            out.append("")
            out.append(
                "> ⚠ **No token set** — why/how rule-rationale subsections "
                "render as placeholders for SonarCloud rules. Set "
                "`SONAR_API_KEY` (or `SONAR_TOKEN`) in your environment to "
                "fetch rule rationale via `api/rules/show`. CodeQL alert "
                "rule help is bundled in the alert JSON and is always "
                "rendered."
            )
    out.append("")
    out.append("---")
    out.append("")
    return out


def _render_combined_source_section(
    *, title: str, source_render_kwargs: dict,
) -> list[str]:
    """Render one source's section (``## <title>`` + demoted body).

    Calls ``render_markdown`` with the given kwargs, strips the
    project-level header, demotes the remaining headings by one level,
    and prepends the ``## <title>`` parent heading. Trailing ``---``
    separators from the per-rule rendering are stripped so we don't get
    two ``---`` lines in a row at the section boundary.
    """
    out: list[str] = [f"## {title}", ""]
    body = render_markdown(**source_render_kwargs)
    body = _strip_project_header(body)
    body = _demote_headings(body, levels=1)
    # Strip trailing --- separators (and surrounding blank lines) so we
    # don't double up at the section boundary. The per-rule renderer
    # ends each rule section with `---`, leaving one at the very end of
    # the body — we replace it with our own section separator below.
    body = body.rstrip()
    while body.endswith("---"):
        body = body[:-3].rstrip()
    out.append(body)
    out.append("")
    out.append("---")
    out.append("")
    return out


def render_combined_markdown(
    *,
    source: str,
    project: str,
    scope: str,
    sonar_issues: list[dict],
    sonar_facets: dict,
    sonar_rules: dict[str, dict],
    codeql_issues: list[dict],
    codeql_rules: dict[str, dict],
    token_present: bool,
    focal_key: str | None,
    clean: bool,
) -> str:
    """Render a combined SonarCloud + CodeQL Markdown report.

    Used by ``export_url`` when both sources have issues. The output has
    a project-level header (title, generated, source, total with source
    counts, token), then a ``## SonarCloud Issues`` section (if
    ``sonar_issues`` is non-empty) and a ``## CodeQL Alerts`` section
    (if ``codeql_issues`` is non-empty). Each source's body is a demoted
    ``render_markdown`` output (headings shifted down by one level so
    they nest cleanly under the parent ``##`` heading).

    The caller is responsible for the silent-drop semantics: only call
    this when at least one source has issues. If both are empty, the
    caller should skip writing the file (per the v1.1.0 spec). If only
    one source has issues, the caller may use the simpler
    ``render_markdown`` path instead — but using this combined renderer
    with a single source also works (it just renders one section).
    """
    distinct_rules = (
        {i.get("rule") for i in sonar_issues if i.get("rule")}
        | {i.get("rule") for i in codeql_issues if i.get("rule")}
    )
    out: list[str] = []
    out.extend(_render_combined_header(
        source=source, project=project, scope=scope,
        sonar_count=len(sonar_issues), codeql_count=len(codeql_issues),
        distinct_rules=len(distinct_rules),
        token_present=token_present, clean=clean,
    ))
    if sonar_issues:
        out.extend(_render_combined_source_section(
            title="SonarCloud Issues",
            source_render_kwargs={
                "source": source, "project": project, "scope": scope,
                "issues": sonar_issues, "facets": sonar_facets,
                "rules": sonar_rules, "token_present": token_present,
                "focal_key": focal_key, "is_local_migration": False,
                "clean": clean,
            },
        ))
    if codeql_issues:
        out.extend(_render_combined_source_section(
            title="CodeQL Alerts",
            source_render_kwargs={
                "source": source, "project": project, "scope": "code-scanning",
                "issues": codeql_issues, "facets": {},
                "rules": codeql_rules, "token_present": True,
                "focal_key": None, "is_local_migration": False,
                "clean": clean,
            },
        ))
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Output path resolver + git-aware default dir discovery
# ---------------------------------------------------------------------------

def _find_git_root(cwd: Path) -> Path | None:
    """Walk up from ``cwd`` looking for a ``.git`` dir or file.

    Returns the directory containing ``.git``, or ``None`` if not in a git
    repo. Used by ``_resolve_default_output_dir`` to decide whether to use
    ``scratch/``, ``cwd``, or ``~/Downloads``.
    """
    current = cwd.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current == current.parent:
            return None  # filesystem root
        current = current.parent


def _resolve_default_output_dir(cwd: Path) -> Path:
    """Resolve the default output directory for non-migration exports.

    Priority (per user spec):
      1. At git root with ``scratch/`` → ``scratch/``
      2. At git root without ``scratch/`` → ``cwd`` (the root)
      3. Inside git project but not root → ``cwd``
      4. Not in git project → ``~/Downloads`` (last resort), or ``cwd`` if
         ``~/Downloads`` doesn't exist

    The ``scratch/`` preference avoids cluttering the project root with
    export files; the git-non-root case lets the user write alongside
    wherever they are (e.g. inside ``archive/0.2.0/``); the last-resort
    ``~/Downloads`` matches the 0.2.x default for users not in a git repo.
    """
    git_root = _find_git_root(cwd)
    if git_root is None:
        # Not in a git project — last resort
        if LAST_RESORT_OUTPUT_DIR.is_dir():
            return LAST_RESORT_OUTPUT_DIR
        print(
            f"  note: not in a git project and {LAST_RESORT_OUTPUT_DIR} not "
            f"found; writing to {cwd}",
            file=sys.stderr,
        )
        return cwd

    if git_root == cwd.resolve():
        # At project root — prefer scratch/, else root itself
        scratch = cwd / SCRATCH_DIR_NAME
        if scratch.is_dir():
            return scratch
        return cwd

    # Inside git project but not at root — output to cwd
    return cwd


def resolve_output_path(
    *,
    explicit: str | None,
    base_dir: Path,
) -> Path:
    """Resolve the output Markdown path.

    - If ``explicit`` is given: use it (creating parent dirs as needed).
    - Else: ``base_dir / issues.md``, auto-incrementing if the file
      already exists (``issues1.md``, ``issues2.md``, …).
    """
    if explicit:
        p = Path(explicit).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / DEFAULT_OUTPUT_NAME
    if not candidate.exists():
        return candidate
    stem = Path(DEFAULT_OUTPUT_NAME).stem
    suffix = Path(DEFAULT_OUTPUT_NAME).suffix
    i = 1
    while True:
        candidate = base_dir / f"{stem}{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# Input resolver: dispatch any input form to a SonarCloud API descriptor
# ---------------------------------------------------------------------------

def resolve_input(
    raw: str | None, *, cwd: Path,
) -> dict:
    """Resolve any input form to a SonarCloud API URL descriptor.

    Priority order:
      1. ``None`` / empty → main branch of CWD's repo
      2. SonarCloud URL (``http(s)://sonarcloud.io/...``) → ``parse_url_input``
      3. GitHub URL (``http(s)://github.com/...``) → ``parse_github_url``
      4. Fuzzy ``owner/repo[/branch]`` → ``resolve_fuzzy``
      5. Single token (``pr``, ``main``, ``<branch>``) → ``resolve_fuzzy``

    Returns a dict with ``{api_url, project, scope, focal_key, source}``.

    Note: local paths are NOT handled here. Local-folder migration is gated
    behind the ``--migrate`` flag in ``main()``, which routes directly to
    ``export_local()``. This avoids positional ambiguity: ``sie <path>``
    is always the output path (with input defaulting to "main of CWD's
    repo"), never a migration input. To migrate, use
    ``sie --migrate <path>``.

    Raises ``ValueError`` on unresolvable input.
    """
    if not raw:
        # No arg = main of CWD's repo. discover_repo will raise if not in a repo.
        repo = discover_repo(cwd)
        descriptor = _build_descriptor(project=repo["project"], scope="main")
        descriptor["source"] = (
            f"<no arg> (CWD repo: {repo['owner']}/{repo['repo']} main)"
        )
        return descriptor

    if looks_like_url(raw):
        # Dispatch on the parsed URL's netloc, NOT substring matching on the
        # raw URL string. CodeQL's `py/incomplete-url-substring-sanitization`
        # flags substring checks (e.g. `"sonarcloud.io" in raw`) because a
        # malicious URL like `http://evil-example.net/sonarcloud.io` would
        # pass the check. urlparse extracts the actual hostname, which is
        # what we want to match against.
        parsed = urllib.parse.urlparse(raw)
        host = parsed.netloc.lower()
        # Strip port if present (e.g. "sonarcloud.io:443" → "sonarcloud.io").
        host = host.split(":", 1)[0]
        if host in ("sonarcloud.io", "www.sonarcloud.io"):
            descriptor = parse_url_input(raw)
            descriptor["source"] = raw
            return descriptor
        if host in ("github.com", "www.github.com"):
            descriptor = parse_github_url(raw)
            descriptor["source"] = raw
            return descriptor
        raise ValueError(
            f"Unsupported URL host: {raw!r}. "
            "Only sonarcloud.io and github.com URLs are supported."
        )

    # Local paths are NOT handled here — they belong to the CLI
    # disambiguation layer (output-path-only mode, or --migrate mode).
    # If resolve_input is called directly with a path-like string, that's
    # a caller bug: raise so it doesn't silently fall through to resolve_fuzzy
    # (which would misclassify `./foo` as owner=".", repo="foo").
    if looks_like_local_path(raw):
        raise ValueError(
            f"Local path {raw!r} is not a valid sie input. "
            "Local paths are output paths (with input defaulting to main of "
            "CWD's repo) or migration inputs (via --migrate). The CLI layer "
            "in main() handles both; resolve_input is for URL/fuzzy inputs only."
        )

    # Fuzzy: owner/repo[/branch], or a single-token shortcut.
    descriptor = resolve_fuzzy(raw, cwd=cwd)
    descriptor["source"] = raw
    return descriptor


def _parse_github_scoping_path(
    parts: list[str], project: str, raw: str,
) -> dict | None:
    """Parse the path-segment scoping (``/pull/N``, ``/tree/branch``, ``/blob/...``,
    ``/security/code-scanning/N``, ``/commit/<sha>``) into a descriptor, or
    return ``None`` if no scoping pattern matches (caller falls back to main).

    Extracted from ``parse_github_url`` to keep cognitive complexity under
    the S3776 / C901 thresholds.
    """
    # /owner/repo/pull/<N>
    if len(parts) >= 4 and parts[2] == "pull":
        try:
            pr_num = int(parts[3])
        except ValueError as e:
            raise ValueError(
                f"Invalid PR number in GitHub URL: {parts[3]!r}"
            ) from e
        return _build_descriptor(
            project=project, scope=f"pr:{pr_num}", pull_request=pr_num,
        )

    # /owner/repo/tree/<branch>  — branch may contain slashes
    # (e.g. feature/sync-rewrite), so join everything from parts[3] onward.
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])
        return _build_descriptor(
            project=project, scope=f"branch:{branch}", branch=branch,
        )

    # /owner/repo/blob/<branch>/<path>  — only the first segment after
    # /blob/ is the branch; the rest is the file path. GitHub branch names
    # can technically contain slashes, but a blob URL's branch is always a
    # single segment because the path after it is what's being viewed. If
    # the branch actually has a slash, use the /tree/ URL form instead.
    if len(parts) >= 4 and parts[2] == "blob":
        return _build_descriptor(
            project=project, scope=f"branch:{parts[3]}", branch=parts[3],
        )

    # /owner/repo/security/code-scanning/<N> — GitHub code-scanning alert.
    # Repo-level alerts (not branch-scoped); the SonarCloud fetch is skipped
    # — we fetch the alert directly via `gh api` instead. The descriptor
    # carries a `code_scanning_alert` field so export_url routes to the
    # GitHub pipeline rather than the SonarCloud pipeline.
    if len(parts) >= 5 and parts[2] == "security" and parts[3] == "code-scanning":
        try:
            alert_num = int(parts[4])
        except ValueError as e:
            raise ValueError(
                f"Invalid code-scanning alert number in GitHub URL: {parts[4]!r}"
            ) from e
        descriptor = _build_descriptor(project=project, scope="main")
        descriptor["code_scanning_alert"] = alert_num
        descriptor["source"] = raw
        return descriptor

    # /owner/repo/commit/<sha> — SonarCloud doesn't index arbitrary SHAs.
    if len(parts) >= 4 and parts[2] == "commit":
        raise ValueError(
            f"Commit-SHA URLs are not supported (SonarCloud indexes branches "
            f"and PRs, not arbitrary commits). Use a branch URL instead: "
            f"https://github.com/{parts[0]}/{parts[1]}/tree/<branch>."
        )

    return None


def parse_github_url(raw: str) -> dict:
    """Parse a GitHub URL into a SonarCloud API descriptor.

    Recognized path patterns:
      - ``/owner/repo``                              → main branch
      - ``/owner/repo/pull/<N>``                     → ``?pullRequest=<N>``
      - ``/owner/repo/tree/<branch>``               → ``?branch=<branch>``
      - ``/owner/repo/blob/<branch>/...``            → ``?branch=<branch>``
      - ``/owner/repo/security/code-scanning/<N>``   → GitHub code-scanning alert
      - ``/owner/repo/commit/<sha>``                 → error (SonarCloud doesn't index SHAs)

    The SonarCloud project key is derived as ``<owner>_<repo>`` (the
    convention for GitHub-integrated SonarCloud projects). Repos with
    custom project keys need an explicit SonarCloud URL.
    """
    parsed = urllib.parse.urlparse(raw)
    if parsed.netloc not in ("github.com", "www.github.com"):
        raise ValueError(f"Not a github.com URL: {raw!r}")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(
            f"GitHub URL missing owner/repo path: {raw!r}. "
            "Expected https://github.com/<owner>/<repo>."
        )

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    project = f"{owner}_{repo}"

    scoped = _parse_github_scoping_path(parts, project, raw)
    if scoped is not None:
        return scoped

    # /owner/repo — default to main.
    return _build_descriptor(project=project, scope="main")


def resolve_fuzzy(raw: str, *, cwd: Path) -> dict:
    """Resolve fuzzy input: ``owner/repo[/branch]``, or single-token
    shortcuts (``pr``, ``main``, ``<branch>``).

    Single-token shortcuts use CWD's repo (via ``discover_repo``). The
    ``pr`` shortcut invokes ``gh pr list`` to find the most recent open PR.
    """
    # Try owner/repo[/branch] first.
    m = FUZZY_OWNER_REPO_RE.match(raw)
    if m:
        owner, repo, branch = m.group(1), m.group(2), m.group(3)
        project = f"{owner}_{repo}"
        if branch:
            return _build_descriptor(
                project=project, scope=f"branch:{branch}",
                branch=branch,
            )
        return _build_descriptor(project=project, scope="main")

    # Single token.
    if "/" in raw:
        # Has slashes but didn't match FUZZY_OWNER_REPO_RE — likely an
        # invalid form like "owner/repo/branch/extra".
        raise ValueError(
            f"Unrecognized input: {raw!r}. Expected ``owner/repo`` or "
            "``owner/repo/branch`` (max 3 slash-separated parts)."
        )

    token = raw.strip()
    if not token:
        # Shouldn't happen (caller filters empty), but guard anyway.
        repo = discover_repo(cwd)
        return _build_descriptor(project=repo["project"], scope="main")

    # ``pr`` shortcut: most recent open PR via `gh`.
    if token == "pr":
        repo = discover_repo(cwd)
        return _resolve_most_recent_pr(repo)

    # ``main`` shortcut: explicit main branch.
    if token == "main":
        repo = discover_repo(cwd)
        return _build_descriptor(project=repo["project"], scope="main")

    # Anything else: treat as a branch name on CWD's repo.
    repo = discover_repo(cwd)
    return _build_descriptor(
        project=repo["project"], scope=f"branch:{token}",
        branch=token,
    )


def _build_descriptor(
    *,
    project: str,
    scope: str,
    focal_key: str | None = None,
    pull_request: str | int | None = None,
    branch: str | None = None,
) -> dict:
    """Build a normalized SonarCloud API URL descriptor.

    Constructs the ``api_url`` from the project + scope, applying the
    standard defaults (``issueStatuses=OPEN``, ``ps=500``).
    """
    params: dict[str, str] = {
        "componentKeys": project,
        "issueStatuses": "OPEN",
        "ps": str(PAGE_SIZE),
    }
    if pull_request is not None:
        params["pullRequest"] = str(pull_request)
    elif branch is not None:
        params["branch"] = branch
    api_url = _build_api_url(params)
    return {
        "api_url": api_url,
        "project": project,
        "scope": scope,
        "focal_key": focal_key,
    }


# ---------------------------------------------------------------------------
# Repo discovery (for fuzzy / no-arg modes)
# ---------------------------------------------------------------------------

def _discover_from_package_json(cwd: Path) -> dict | None:
    """Try to discover owner/repo from ``./package.json`` → ``repository.url``.

    Returns ``{"owner", "repo", "project"}`` on success, ``None`` if no
    package.json is present, the URL isn't a GitHub URL, or parsing fails
    (any of which means: fall through to the next discovery source).
    """
    pkg_path = cwd / "package.json"
    if not pkg_path.is_file():
        return None
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        repo_field = data.get("repository", "")
        if isinstance(repo_field, dict):
            repo_url = repo_field.get("url", "")
        else:
            repo_url = str(repo_field)
        owner, repo = _parse_github_url(repo_url)
        if owner and repo:
            return {"owner": owner, "repo": repo, "project": f"{owner}_{repo}"}
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _discover_from_pyproject(cwd: Path) -> dict | None:
    """Try to discover owner/repo from ``./pyproject.toml``.

    Regex-parses any quoted ``https://github.com/owner/repo`` URL (no
    ``tomllib`` dependency — keeps Python 3.10 support). Returns
    ``{"owner", "repo", "project"}`` on success, ``None`` otherwise.
    """
    pp_path = cwd / "pyproject.toml"
    if not pp_path.is_file():
        return None
    try:
        text = pp_path.read_text(encoding="utf-8")
        m = re.search(
            r"[\"']https?://github\.com/"
            r"([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?[\"']",
            text,
        )
        if m:
            owner, repo = m.group(1), m.group(2)
            return {"owner": owner, "repo": repo, "project": f"{owner}_{repo}"}
    except OSError:
        pass
    return None


def _discover_from_git_remote(cwd: Path) -> dict | None:
    """Try to discover owner/repo from ``git remote get-url origin``.

    The catch-all for any git checkout (no package.json or pyproject.toml
    required). Returns ``{"owner", "repo", "project"}`` on success, ``None``
    if git isn't installed, the command fails, or the remote isn't GitHub.
    """
    if not shutil.which("git"):
        return None
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        if proc.returncode == 0:
            owner, repo = _parse_github_url(proc.stdout.strip())
            if owner and repo:
                return {
                    "owner": owner, "repo": repo,
                    "project": f"{owner}_{repo}",
                }
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def discover_repo(cwd: Path) -> dict:
    """Discover the GitHub owner/repo for ``cwd``.

    Discovery sources (in priority order):
      1. ``./package.json`` → ``repository.url`` field (JS projects)
      2. ``./pyproject.toml`` → any ``github.com/owner/repo`` URL (Python)
      3. ``git remote get-url origin`` (catch-all for git repos)

    Returns ``{"owner": str, "repo": str, "project": str}`` where
    ``project`` is the SonarCloud project key (``<owner>_<repo>``).

    Raises ``RuntimeError`` if no repo info can be discovered.
    """
    for discover in (
        _discover_from_package_json,
        _discover_from_pyproject,
        _discover_from_git_remote,
    ):
        result = discover(cwd)
        if result:
            return result
    raise RuntimeError(
        "Could not discover GitHub repo info from CWD. Tried: "
        "package.json, pyproject.toml, git remote. "
        "Pass an explicit URL or ``owner/repo`` instead."
    )


def _parse_github_url(url: str) -> tuple[str, str]:
    """Parse ``owner``/``repo`` from a GitHub URL or SSH string.

    Handles:
      - ``https://github.com/owner/repo``
      - ``https://github.com/owner/repo.git``
      - ``git+https://github.com/owner/repo.git``
      - ``git@github.com:owner/repo.git``
      - ``ssh://git@github.com/owner/repo.git``

    Returns ``("", "")`` if the input doesn't match a GitHub form.
    """
    if not url:
        return "", ""
    url = url.strip()
    # Strip the ``git+`` prefix used in package.json repository URLs.
    url = url.removeprefix("git+")
    m = GITHUB_HTTPS_RE.match(url)
    if m:
        return m.group(1), m.group(2)
    m = GITHUB_SSH_RE.match(url)
    if m:
        return m.group(1), m.group(2)
    return "", ""


def _resolve_most_recent_pr(repo: dict) -> dict:
    """Resolve the most recent open PR for ``repo`` via the ``gh`` CLI.

    Runs ``gh pr list --state open --limit 1 --json number,headRefName``
    in the current working directory. Requires ``gh`` on PATH and
    authenticated (``gh auth login``).

    Raises ``RuntimeError`` if ``gh`` is not installed, not authenticated,
    or returns no open PRs.
    """
    if not shutil.which("gh"):
        raise RuntimeError(
            "The ``pr`` shortcut requires the GitHub CLI (`gh`). "
            "Install from https://cli.github.com, then `gh auth login`. "
            "For a specific PR, use the URL form: "
            f"sie https://github.com/{repo['owner']}/{repo['repo']}/pull/<N>"
        )
    try:
        proc = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "open",
                "--limit", "1",
                "--json", "number,headRefName,title",
            ],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise RuntimeError(f"`gh pr list` invocation failed: {e}") from e

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            f"`gh pr list` failed (exit {proc.returncode}): {stderr}\n"
            "Hint: run `gh auth login` to authenticate."
        )

    try:
        prs = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"`gh pr list` returned non-JSON output: {proc.stdout!r}"
        ) from e

    if not prs:
        raise RuntimeError(
            f"No open PRs found for {repo['owner']}/{repo['repo']}. "
            "Use a branch name or the main branch instead."
        )

    pr = prs[0]
    pr_num = pr.get("number")
    if not pr_num:
        raise RuntimeError(f"`gh pr list` returned a PR without a number: {pr!r}")

    print(
        f"  most recent open PR: #{pr_num} — {pr.get('title', '(no title)')}",
        file=sys.stderr,
    )
    return _build_descriptor(
        project=repo["project"], scope=f"pr:{pr_num}",
        pull_request=pr_num,
    )


# ---------------------------------------------------------------------------
# Export pipeline (URL -> fetch -> render -> write)
# ---------------------------------------------------------------------------

def _run_summary_mode(
    api_url: str, project: str, scope: str, focal_key: str | None, token: str,
) -> int:
    """Cheap triage: fetch facets + first page, print summary to stdout, return exit code.

    Extracted from ``export_url`` to reduce cognitive complexity (S3776).
    v1.1.0: also fetches repo-wide open CodeQL alert count (best-effort,
    silent if gh unavailable) and prints it after the SonarCloud sections.
    """
    summary_url = _ensure_facets(api_url)
    print("Fetching facets + first page…", file=sys.stderr)
    try:
        data = _api_get(summary_url, token)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    total = int(data.get("total", 0))
    facets = {
        f["property"]: f.get("values", [])
        for f in data.get("facets", []) or []
    }
    issues = list(data.get("issues", []))
    # v1.1.0: best-effort CodeQL count for the triage summary.
    print("Fetching repo-wide open CodeQL alert count (best-effort)…", file=sys.stderr)
    codeql_issues, _codeql_rules = _fetch_code_scanning_for_project(project)
    codeql_count = len(codeql_issues)
    _print_summary_stdout(
        project=project, scope=scope, total=total,
        facets=facets, sample_issues=issues[:3],
        codeql_count=codeql_count,
    )
    return 0


def _fetch_issues_or_fail(
    api_url: str, token: str, *, msg: str = "Fetching issues…",
) -> tuple[list[dict], dict] | None:
    """Fetch issues + facets, or return ``None`` (after printing the error) on failure.

    Extracted from ``export_url`` to reduce cognitive complexity (S3776) —
    the try/except blocks were repeating across the main fetch + focal fallback.
    """
    print(msg, file=sys.stderr)
    try:
        return fetch_issues(api_url, token)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def _fetch_with_focal_fallback(
    api_url: str, project: str, focal_key: str | None, token: str,
) -> tuple[list[dict], dict, int | None]:
    """Fetch issues, falling back to all-OPEN if focal key came up empty.

    Returns ``(issues, facets, exit_code)``. ``exit_code`` is ``None`` on
    success (caller continues), or an int (caller returns it immediately).
    """
    result = _fetch_issues_or_fail(api_url, token)
    if result is None:
        return [], {}, 2
    issues, facets = result

    if focal_key and not issues and project:
        print(
            "  focal issue not in initial fetch (likely auth-boundary); "
            "fetching all OPEN issues for the project…",
            file=sys.stderr,
        )
        fallback_url = _build_api_url({
            "componentKeys": project,
            "issueStatuses": "OPEN",
            "ps": str(PAGE_SIZE),
        })
        result = _fetch_issues_or_fail(fallback_url, token, msg="")
        if result is None:
            return [], {}, 2
        issues, facets = result

    return issues, facets, None


def _fetch_rule_metadata(
    issues: list[dict], token: str, clean: bool,
) -> dict[str, dict]:
    """Fetch why/how rule metadata for each distinct rule in ``issues``.

    Skipped when ``clean=True`` (the content would be dropped by
    ``render_markdown`` anyway) or when no token is available.
    """
    if not token or clean:
        return {}
    distinct_rules = {i.get("rule") for i in issues if i.get("rule")}
    organization = next(
        (i.get("organization") for i in issues if i.get("organization")),
        "",
    )
    if distinct_rules:
        print(
            f"Fetching rule metadata for {len(distinct_rules)} rule(s)…",
            file=sys.stderr,
        )
    rules: dict[str, dict] = {}
    for rk in sorted(distinct_rules):
        why_md, how_md = fetch_rule_md(rk, organization, token)
        rules[rk] = {"why": why_md, "how": how_md}
    return rules


def _run_code_scanning_mode(
    descriptor: dict, *, output_path: str | None, cwd: Path | None,
) -> int:
    """Fetch + render a single GitHub code-scanning alert via `gh api`.

    Extracted from ``export_url`` to keep cognitive complexity under S3776.
    The descriptor must carry ``code_scanning_alert`` (the alert number)
    and ``owner``/``repo`` (stashed by ``parse_github_url``).
    """
    # Recover owner/repo from the project key (``<owner>_<repo>``).
    project = descriptor["project"]
    owner, _, repo = project.partition("_")
    alert_num = descriptor["code_scanning_alert"]
    source = descriptor.get("source", "")
    print(
        f"Project: {project}  Code-scanning alert: #{alert_num}",
        file=sys.stderr,
    )
    print("Fetching alert via `gh api`…", file=sys.stderr)
    try:
        alert = fetch_code_scanning_alert(owner, repo, alert_num)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    markdown = render_code_scanning_markdown(
        source=source, owner=owner, repo=repo, alert=alert,
    )
    out_path = resolve_output_path(
        explicit=output_path,
        base_dir=_resolve_default_output_dir(cwd or Path.cwd()),
    )
    out_path.write_text(markdown, encoding="utf-8")
    print(f"\nWrote: {out_path}", file=sys.stderr)
    return 0


def _render_export_markdown(
    *,
    source: str,
    project: str,
    scope: str,
    sonar_issues: list[dict],
    sonar_facets: dict,
    sonar_rules: dict[str, dict],
    codeql_issues: list[dict],
    codeql_rules: dict[str, dict],
    token_present: bool,
    focal_key: str | None,
    clean: bool,
) -> str | None:
    """Pick the right renderer and return the Markdown, or ``None`` if empty.

    Returns ``None`` when both ``sonar_issues`` and ``codeql_issues`` are
    empty — the caller uses this to skip the write and print a "no
    issues found" message instead (per the v1.1.0 spec).

    Three render paths:
      - Both sources non-empty → ``render_combined_markdown`` (project
        header + ``## SonarCloud Issues`` + ``## CodeQL Alerts``)
      - SonarCloud only → ``render_markdown`` (unchanged v1.0.0 layout)
      - CodeQL only → ``render_markdown`` with ``scope="code-scanning"``

    Extracted from ``export_url`` to keep cognitive complexity under
    the S3776 threshold (15) — the three-way branch is its own natural
    function.
    """
    has_sonar = bool(sonar_issues)
    has_codeql = bool(codeql_issues)
    if not has_sonar and not has_codeql:
        return None
    if has_sonar and has_codeql:
        return render_combined_markdown(
            source=source, project=project, scope=scope,
            sonar_issues=sonar_issues, sonar_facets=sonar_facets,
            sonar_rules=sonar_rules,
            codeql_issues=codeql_issues, codeql_rules=codeql_rules,
            token_present=token_present, focal_key=focal_key, clean=clean,
        )
    if has_sonar:
        return render_markdown(
            source=source, project=project, scope=scope,
            issues=sonar_issues, facets=sonar_facets, rules=sonar_rules,
            token_present=token_present, focal_key=focal_key,
            is_local_migration=False, clean=clean,
        )
    # CodeQL-only path
    return render_markdown(
        source=source, project=project, scope="code-scanning",
        issues=codeql_issues, facets={}, rules=codeql_rules,
        token_present=True, focal_key=None,
        is_local_migration=False, clean=clean,
    )


def export_url(
    descriptor: dict,
    *,
    output_path: str | None,
    summary_mode: bool = False,
    cwd: Path | None = None,
    clean: bool = False,
) -> int:
    """Run the full export pipeline for a resolved descriptor.

    ``descriptor`` is the dict returned by ``resolve_input`` (or
    ``parse_url_input`` / ``parse_github_url`` / ``_build_descriptor``):
    ``{api_url, project, scope, focal_key}``.

    If the descriptor carries a ``code_scanning_alert`` field (set when the
    input was a ``https://github.com/owner/repo/security/code-scanning/<N>``
    URL), this routes to the single-alert GitHub code-scanning pipeline
    (``gh api``) instead of the SonarCloud pipeline. That's the v1.0.0
    legacy path — the alert is fetched by number, no auto-discovery.

    Otherwise (the v1.1.0 default), the pipeline fetches SonarCloud
    issues for the resolved scope (branch/PR/main) AND repo-wide open
    CodeQL alerts via ``_fetch_code_scanning_for_project``. The CodeQL
    fetch is best-effort: if ``gh`` isn't available, the capability is
    silently dropped and the SonarCloud-only path is used. If both
    sources come back empty, no file is written (per the v1.1.0 spec);
    a "no open issues found" message is printed to stderr.

    ``cwd`` is used to resolve the default output directory via
    ``_resolve_default_output_dir``. If ``None``, defaults to ``Path.cwd()``.

    Returns the process exit code (0 on success, 2 on API error).

    The pipeline is assembled from helpers, each handling one phase
    (code-scanning mode, summary mode, issue fetch + focal fallback,
    rule-metadata fetch, CodeQL auto-discovery, render + write).
    Extracted to keep cognitive complexity under the S3776 threshold.
    """
    if "code_scanning_alert" in descriptor:
        return _run_code_scanning_mode(
            descriptor, output_path=output_path, cwd=cwd,
        )

    token = get_token()
    api_url = descriptor["api_url"]
    project = descriptor["project"]
    scope = descriptor["scope"]
    focal_key = descriptor.get("focal_key")
    source = descriptor.get("source", api_url)

    print(
        f"Project: {project}  Scope: {scope}"
        + (f"  Focal: {focal_key}" if focal_key else ""),
        file=sys.stderr,
    )
    print(
        f"Token: {'present' if token else 'absent (public-project mode)'}",
        file=sys.stderr,
    )

    if summary_mode:
        return _run_summary_mode(api_url, project, scope, focal_key, token)

    sonar_issues, sonar_facets, rc = _fetch_with_focal_fallback(
        api_url, project, focal_key, token,
    )
    if rc is not None:
        return rc

    sonar_rules = _fetch_rule_metadata(sonar_issues, token, clean)

    # v1.1.0: best-effort repo-wide CodeQL auto-discovery. Silent drop
    # if gh isn't available — the SonarCloud-only path proceeds below.
    print("Fetching repo-wide open CodeQL alerts (best-effort)…", file=sys.stderr)
    codeql_issues, codeql_rules = _fetch_code_scanning_for_project(project)
    if codeql_issues:
        print(
            f"  CodeQL: {len(codeql_issues)} alert(s) across "
            f"{len(codeql_rules)} rule(s)",
            file=sys.stderr,
        )
    else:
        print("  CodeQL: 0 alerts (gh unavailable or no open alerts)", file=sys.stderr)

    markdown = _render_export_markdown(
        source=source, project=project, scope=scope,
        sonar_issues=sonar_issues, sonar_facets=sonar_facets,
        sonar_rules=sonar_rules,
        codeql_issues=codeql_issues, codeql_rules=codeql_rules,
        token_present=bool(token), focal_key=focal_key, clean=clean,
    )
    if markdown is None:
        print(
            "\nNo open issues found "
            f"(SonarCloud: {len(sonar_issues)}, CodeQL: {len(codeql_issues)}).",
            file=sys.stderr,
        )
        return 0

    out_path = resolve_output_path(
        explicit=output_path,
        base_dir=_resolve_default_output_dir(cwd or Path.cwd()),
    )
    out_path.write_text(markdown, encoding="utf-8")
    print(f"\nWrote: {out_path}", file=sys.stderr)
    return 0


def _ensure_facets(api_url: str) -> str:
    """Return ``api_url`` with ``&facets=rules,severities,types`` added."""
    parsed = urllib.parse.urlparse(api_url)
    qs_lists = urllib.parse.parse_qs(parsed.query)
    qs_lists["facets"] = ["rules,severities,types"]
    qs_lists["ps"] = ["1"]  # we only need facets + total, not issue bodies
    qs = {k: v[0] if len(v) == 1 else ",".join(v) for k, v in qs_lists.items()}
    new_query = urllib.parse.urlencode(qs, safe=":,")
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _print_severity_section(sev: list) -> None:
    """Print the Severities subsection of the triage summary."""
    sev_sorted = sorted(
        sev, key=lambda v: SEVERITY_ORDER.get(v.get("val", ""), 99)
    )
    print("Severities:")
    for s in sev_sorted:
        print(f"  {str(s.get('val', '')):<10} {s.get('count', 0)}")
    print()


def _print_type_section(typ: list) -> None:
    """Print the Types subsection of the triage summary."""
    print("Types:")
    for t in sorted(typ, key=lambda v: -v.get("count", 0)):
        print(f"  {str(t.get('val', '')):<15} {t.get('count', 0)}")
    print()


def _print_rules_section(rul: list) -> None:
    """Print the Top rules subsection of the triage summary."""
    top = sorted(rul, key=lambda v: (-v.get("count", 0), v.get("val", "")))[:15]
    print("Top rules:")
    for r in top:
        print(f"  {r.get('val', '?'):<25} {r.get('count', 0)}×")
    print()


def _print_sample_section(sample_issues: list[dict]) -> None:
    """Print the Sample (first 3) subsection of the triage summary."""
    print("Sample (first 3):")
    for i in sample_issues:
        comp = i.get("component", "")
        line = i.get("line")
        print(
            f"  [{i.get('severity', '?'):<8}] "
            f"{i.get('rule', '?'):<25} "
            f"{comp}:{line or 'unknown'}"
        )
        msg = i.get("message", "")
        if msg:
            print(f"           {msg[:120]}")


def _print_summary_stdout(
    *,
    project: str,
    scope: str,
    total: int,
    facets: dict,
    sample_issues: list[dict],
    codeql_count: int = 0,
) -> None:
    """Print a compact triage summary to stdout (no file written).

    Each subsection (severities, types, rules, sample) is rendered by its
    own helper to keep cognitive complexity under the S3776 threshold.
    v1.1.0: a final ``CodeQL Alerts:`` line prints the repo-wide open
    count (0 if gh unavailable — silent drop, consistent with the
    full-export path).
    """
    print(f"# {project} ({scope}) — {total} SonarCloud issue(s)")
    print()

    sev = facets.get("severities", [])
    typ = facets.get("types", [])
    rul = facets.get("rules", [])

    if sev:
        _print_severity_section(sev)
    if typ:
        _print_type_section(typ)
    if rul:
        _print_rules_section(rul)
    if sample_issues:
        _print_sample_section(sample_issues)

    # CodeQL line always prints (even when 0) so the user knows the
    # capability was attempted. The full-export path also always prints
    # the CodeQL status line, so the summary matches.
    print(f"CodeQL Alerts: {codeql_count} open (repo-wide, via gh api)")
    print()


# ---------------------------------------------------------------------------
# Local-folder migration pipeline
# ---------------------------------------------------------------------------

def _looks_like_issues_folder(path: Path) -> bool:
    """Check if ``path`` looks like a 0.2.x issues export folder.

    Heuristic: has at least one subdirectory containing an ``L*.json`` file
    (matching ``ISSUE_FILE_RE``). This is the shape documented in
    ``sonarqube-workflow-SKILL.md``: ``<folder>/<category>/L{line}.json``.
    """
    if not path.is_dir():
        return False
    for child in path.iterdir():
        if child.is_dir():
            for f in child.iterdir():
                if ISSUE_FILE_RE.match(f.name):
                    return True
    return False


def _discover_migrate_folder(cwd: Path) -> tuple[Path, Path]:
    """Auto-discover the issues/ folder to migrate and the output directory.

    Returns ``(migrate_folder, output_dir)``.

    Cases (per user spec):
      1. cwd contains an ``issues/`` subfolder that looks like an issues
         export:
           - migrate: ``cwd/issues/``
           - output: ``cwd`` (alongside the issues/ subfolder)
           - safety: refuse if cwd has ``.git/`` or ``cwd/issues.md``
             already exists
      2. cwd itself looks like an issues folder:
           - migrate: ``cwd``
           - output: ``cwd.parent`` (alongside the issues folder)
           - safety: refuse if cwd has ``.git/`` or
             ``cwd.parent/issues.md`` already exists
      3. Neither → error with helpful message

    The ``.git/`` refusal prevents auto-discovery from doing something
    surprising at a git root. The ``issues.md`` refusal prevents
    clobbering an existing migration output. (v1.1.0: was
    ``sonar-issues.md``; renamed in lockstep with DEFAULT_OUTPUT_NAME.)
    """
    # Safety: refuse at git root (auto-discovery at a git root is too
    # risky — too many subfolders could match).
    if (cwd / ".git").exists():
        raise RuntimeError(
            f"Refusing to auto-discover migration folder at git root {cwd}. "
            "Pass an explicit path: sie -m /path/to/issues/folder"
        )

    # Case 1: cwd contains an `issues/` subfolder
    issues_subfolder = cwd / ISSUES_DIR_NAME
    if issues_subfolder.is_dir() and _looks_like_issues_folder(issues_subfolder):
        if (cwd / DEFAULT_OUTPUT_NAME).exists():
            raise RuntimeError(
                f"Refusing to migrate: {cwd / DEFAULT_OUTPUT_NAME} already "
                "exists. Remove it first, or pass an explicit output path: "
                f"sie -m {issues_subfolder} /tmp/out.md"
            )
        return issues_subfolder, cwd

    # Case 2: cwd itself looks like an issues folder
    if _looks_like_issues_folder(cwd):
        parent = cwd.parent
        if (parent / DEFAULT_OUTPUT_NAME).exists():
            raise RuntimeError(
                f"Refusing to migrate: {parent / DEFAULT_OUTPUT_NAME} already "
                "exists. Remove it first, or pass an explicit output path: "
                f"sie -m {cwd} /tmp/out.md"
            )
        return cwd, parent

    # Case 3: neither
    raise RuntimeError(
        f"Could not auto-discover an issues export folder at {cwd}. "
        "Either:\n"
        "  - run `sie -m` from a folder that contains an `issues/` "
        "subfolder, or\n"
        "  - run `sie -m` from inside an issues export folder, or\n"
        "  - pass an explicit path: sie -m /path/to/issues/folder"
    )


def export_local(
    folder: Path | None,
    *,
    output_path: str | None,
    cwd: Path,
) -> int:
    """Run the local-folder migration pipeline.

    If ``folder`` is ``None``, auto-discover using
    ``_discover_migrate_folder(cwd)``. Otherwise, use the explicit path.
    """
    if folder is None:
        try:
            folder, default_output_dir = _discover_migrate_folder(cwd)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        if not folder.exists():
            print(f"Error: path does not exist: {folder}", file=sys.stderr)
            return 1
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            return 1
        default_output_dir = folder.parent

    print(f"Parsing local export at: {folder}", file=sys.stderr)
    issues, rules = parse_local_export(folder)
    print(
        f"  found {len(issues)} issue(s) across "
        f"{len({i.get('rule') for i in issues if i.get('rule')})} rule(s)",
        file=sys.stderr,
    )

    if not issues:
        print(
            "  warning: no L*.json files found — is this a 0.2.x export folder?",
            file=sys.stderr,
        )

    # Derive project from issue components if possible.
    project = ""
    for i in issues:
        comp = i.get("component", "")
        if ":" in comp:
            project = comp.split(":", 1)[0]
            break

    markdown = render_markdown(
        source=str(folder),
        project=project,
        scope="local-export",
        issues=issues,
        facets={},  # computed from issues inside render_markdown
        rules=rules,
        token_present=True,  # why/how came from disk; suppress token warning
        focal_key=None,
        is_local_migration=True,
    )

    out_path = resolve_output_path(
        explicit=output_path, base_dir=default_output_dir,
    )
    out_path.write_text(markdown, encoding="utf-8")
    print(f"\nWrote: {out_path}", file=sys.stderr)
    print(
        "Original per-issue JSONs and why/how files left untouched "
        "(migration is nondestructive).",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser.

    The epilog is deliberately short — the full input-forms reference,
    disambiguation table, and examples live in README.md. The ``-h`` output
    should fit on one screen.
    """
    parser = argparse.ArgumentParser(
        prog="sie",
        description=(
            f"sie — sonar-issue-exporter v{VERSION}. Fetch SonarCloud "
            "issues and render them into a single Markdown file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
quick examples:
  sie                                    # main of CWD -> scratch/ or cwd
  sie amokprime/linebyline               # fuzzy owner/repo
  sie https://github.com/owner/repo/pull/11
  sie -s pr                              # triage most recent PR (via gh)
  sie -m                                 # auto-discover issues/ folder
  sie -m /path/to/issues                 # migrate explicit folder

See README.md for the full input forms, positional disambiguation, and
repo discovery rules.

environment:
  SONAR_API_KEY  SonarCloud API key (preferred). Export in your shell rc.
  SONAR_TOKEN    Fallback env var name (SonarQube convention).

exit codes: 0 success, 1 usage/write error, 2 API/transport error.
""",
    )
    parser.add_argument(
        "url_or_path",
        nargs="?",
        help=(
            "SonarCloud URL, GitHub URL, fuzzy owner/repo[/branch], "
            "single-token shortcut (pr/main/<branch>), or — if it looks "
            "like a local path AND -m is not set — the output Markdown "
            "path. Defaults to 'main of CWD's repo' when omitted."
        ),
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        help=(
            "Optional output Markdown path. Defaults to scratch/ (git root) "
            "or cwd (git non-root) or ~/Downloads (last resort). "
            "Auto-incrementing."
        ),
    )
    parser.add_argument(
        "-s", "--summary",
        action="store_true",
        help="Cheap triage: fetch facets only, print to stdout, no file.",
    )
    parser.add_argument(
        "-m", "--migrate",
        action="store_true",
        help=(
            "Migrate a 0.2.x issues folder to single-file Markdown. "
            "With no path arg, auto-discovers issues/ in cwd or cwd itself."
        ),
    )
    parser.add_argument(
        "-d", "--debug-env",
        action="store_true",
        help=(
            "Print token env var diagnostic (checks SONAR_API_KEY and "
            "SONAR_TOKEN: not set / empty / set with N chars). Use this to "
            "diagnose 'Token: absent' when you believe the var is set."
        ),
    )
    parser.add_argument(
        "-c", "--clean",
        action="store_true",
        help=(
            "Clean mode: silently drop the Why/How rule-rationale sections "
            "from the output (no placeholder, no warning). Skips the "
            "api/rules/show fetch entirely. Use this to avoid pushing "
            "possibly-licensed Sonar content to a chat."
        ),
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"sie {VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    pos1 = args.url_or_path  # may be None
    pos2 = args.output_path  # may be None
    cwd = Path.cwd()

    # -d / --debug-env: print env var diagnostic and exit.
    if args.debug_env:
        return _debug_env()

    # -m / --migrate mode: pos1 is the migration folder (or None for
    # auto-discovery), pos2 is the optional output path.
    if args.migrate:
        if args.summary:
            print(
                "Error: --summary is not valid with --migrate "
                "(summary mode is for URLs and fuzzy inputs).",
                file=sys.stderr,
            )
            return 1
        folder = Path(pos1).expanduser() if pos1 else None
        return export_local(folder, output_path=pos2, cwd=cwd)

    # Default mode: figure out input vs output from the positionals.
    #
    # Disambiguation rule: if pos1 looks like a local path (starts with
    # /, ~, ./, ../, or a Windows drive letter), treat it as the OUTPUT
    # path with input defaulting to "main of CWD's repo". This makes
    # `sie ~/my-report.md` work as expected (main of CWD -> ~/my-report.md)
    # instead of trying to migrate ~/my-report.md as a folder.
    #
    # Two positionals where pos1 looks like a local path is ambiguous —
    # reject with a hint to use -m.
    if pos1 and looks_like_local_path(pos1) and pos2:
        print(
            f"Error: ambiguous positionals — first positional {pos1!r} "
            "looks like a local path, but you also gave a second "
            f"positional {pos2!r}.\n"
            "  If you want to migrate a local folder: "
            f"sie -m {pos1!r} {pos2!r}\n"
            "  If you want to fetch issues and write to a custom "
            "output: pass a URL or fuzzy input as the first positional, "
            f"e.g. sie amokprime/linebyline {pos2!r}",
            file=sys.stderr,
        )
        return 1

    if pos1 and looks_like_local_path(pos1):
        # pos1 is the output path; input defaults to main of CWD's repo.
        try:
            descriptor = resolve_input(None, cwd=cwd)
        except (ValueError, RuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return export_url(
            descriptor,
            output_path=pos1,
            summary_mode=args.summary,
            cwd=cwd,
            clean=args.clean,
        )

    # Standard mode: pos1 is input (URL/fuzzy/None), pos2 is output.
    try:
        descriptor = resolve_input(pos1, cwd=cwd)
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return export_url(
        descriptor,
        output_path=pos2,
        summary_mode=args.summary,
        cwd=cwd,
        clean=args.clean,
    )


if __name__ == "__main__":
    sys.exit(main())
