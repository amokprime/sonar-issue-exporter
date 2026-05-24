#!/usr/bin/env python3
"""
Export all three tabs of a SonarCloud issue from a browser URL.

Reads BEARER_TOKEN from .env (or environment variables).
Accepts a SonarCloud issue URL as a command-line argument, or from the
RAW_URL environment variable / .env file.

For each run, creates a subfolder named after the issue's message, then saves:
  - where.json  (the stripped-down issue data)
  - why.md      (the "Why is this an issue?" explanation)
  - how.md      (the "How can I fix it?" guidance)

Files for tabs that have no content on SonarCloud are skipped (not written)
instead of being created as empty 0 KB files. A message explains which tabs
were skipped and why.

Duplicate issue names get a counter suffix (e.g. "issue_name", "issue_name_1", ...).
"""

import os
import sys
import json
import re
import html as html_mod
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

# Try to use html2text for better Markdown conversion; fall back to simple stripping.
try:
    import html2text
    _HTML2TEXT = html2text.HTML2Text()
    _HTML2TEXT.body_width = 0
    _HTML2TEXT.ignore_links = False
    def html_to_md(html: str) -> str:
        return _HTML2TEXT.handle(html).strip()
except ImportError:
    def html_to_md(html: str) -> str:
        """Basic HTML to Markdown-like text: remove tags, decode entities, replace <br> with newline."""
        text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_mod.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


# --- Configuration (via .env file) -------------------------------------------
def load_env(env_path: Path = Path(".env")):
    """Load key=value pairs from a .env file into os.environ."""
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value


def find_env_file() -> Optional[Path]:
    """Find the .env file, checking the current directory first, then the script's directory."""
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    script_env = Path(__file__).parent / ".env"
    if script_env.exists():
        return script_env
    return None


def load_config() -> str:
    """Load .env and return the BEARER_TOKEN. Exits on failure."""
    env_file = find_env_file()
    if env_file:
        load_env(env_file)
    else:
        print("Note: no .env file found in current directory or script directory.", file=sys.stderr)

    token = os.getenv("BEARER_TOKEN")
    if not token:
        print("ERROR: BEARER_TOKEN not set. Add it to .env or set the environment variable.", file=sys.stderr)
        sys.exit(1)
    return token


# --- Helper: API call --------------------------------------------------------
BASE = "https://sonarcloud.io/api"


def api_get(endpoint: str, params: dict, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE}/{endpoint}"
    resp = requests.get(url, params=params, headers=headers)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"\nAPI ERROR: {e}", file=sys.stderr)
        print("Response body:", resp.text, file=sys.stderr)
        raise
    return resp.json()


# --- Folder naming -----------------------------------------------------------
def sanitise_folder_name(raw: str, max_len: int = 80) -> str:
    """
    Convert an issue message into a folder-safe name.
    - Replace spaces with underscores
    - Remove characters illegal on Windows/macOS/Linux
    - Collapse multiple underscores
    - Truncate to max_len
    """
    name = raw.replace(' ', '_')
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip(' .-')
    if len(name) > max_len:
        name = name[:max_len].rstrip('_')
    return name or "issue"


def create_unique_folder(base_name: str) -> Path:
    """Create a new folder, appending _1, _2, ... if the name already exists."""
    folder = Path(base_name)
    counter = 1
    while folder.exists():
        folder = Path(f"{base_name}_{counter}")
        counter += 1
    folder.mkdir(parents=True, exist_ok=False)
    return folder


# --- File writing ------------------------------------------------------------
def write_file(folder: Path, filename: str, content: str, tab_label: str = "") -> bool:
    """Write content to file. Skip if content is empty/whitespace-only."""
    if not content or not content.strip():
        label = f' "{tab_label}" tab' if tab_label else ''
        print(f"  Skipped -> {filename} (no content available for{label} on SonarCloud)")
        return False
    filepath = folder / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Saved -> {filepath}")
    return True


# --- URL parsing -------------------------------------------------------------
def parse_issue_url(raw_url: str) -> Tuple[str, str, Optional[str], Optional[str]]:
    """Parse a SonarCloud URL into (component_key, issue_key, pull_request, branch)."""
    parsed = urlparse(raw_url)
    qs = parse_qs(parsed.query)

    component_key = qs.get("id", [None])[0]
    issue_key     = qs.get("open", [None])[0]
    pull_request  = qs.get("pullRequest", [None])[0]
    branch        = qs.get("branch", [None])[0]

    return component_key, issue_key, pull_request, branch


def resolve_url() -> str:
    """Get the SonarCloud URL from CLI args or RAW_URL env var. Exits on failure."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    raw_url = os.getenv("RAW_URL")
    if not raw_url:
        print("ERROR: provide a SonarCloud issue URL as an argument, or set RAW_URL in .env.", file=sys.stderr)
        sys.exit(1)
    return raw_url


# --- Issue fetching ----------------------------------------------------------
KEEP_FIELDS = {
    "rule", "severity", "type", "component", "line", "textRange",
    "message", "flows", "impacts", "cleanCodeAttribute", "cleanCodeAttributeCategory"
}


def fetch_issue(component_key: str, issue_key: str, token: str,
                pull_request: Optional[str] = None,
                branch: Optional[str] = None) -> Dict:
    """Fetch an issue from SonarCloud and return the cleaned issue dict.

    Also returns rule_key, organization, and issue_message via the dict.
    Exits on failure.
    """
    search_params = {
        "issues": issue_key,
        "componentKeys": component_key,
    }
    if pull_request:
        search_params["pullRequest"] = pull_request
    if branch:
        search_params["branch"] = branch

    issue_data = api_get("issues/search", search_params, token)
    issues = issue_data.get("issues", [])
    if not issues:
        print("ERROR: issue not found.", file=sys.stderr)
        sys.exit(1)

    issue = issues[0]
    rule_key = issue.get("rule")
    if not rule_key:
        print("ERROR: rule key missing from issue.", file=sys.stderr)
        sys.exit(1)

    clean_issue = {k: issue[k] for k in KEEP_FIELDS if k in issue}
    clean_issue["_rule_key"] = rule_key
    clean_issue["_organization"] = issue.get("organization", "")
    clean_issue["_message"] = issue.get("message", "unknown_issue")
    return clean_issue


# --- Rule description parsing ------------------------------------------------
def extract_rule_descriptions(rule: dict) -> Tuple[str, str]:
    """Extract the 'why' and 'how' HTML content from a rule dict.

    Returns (why_html, how_html).
    """
    sections = {s["key"]: s["content"] for s in rule.get("descriptionSections", [])}

    if sections:
        intro = sections.get("introduction", "")
        root  = sections.get("root_cause", "")
        why_html = f"{intro}\n\n{root}".strip()
        how_html = sections.get("how_to_fix", "")

        if not why_html:
            why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
    else:
        why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
        how_html = ""

    return why_html, how_html


def fetch_rule_details(rule_key: str, organization: str, token: str) -> Tuple[str, str]:
    """Fetch rule details and return (why_md, how_md)."""
    rule_data = api_get("rules/show", {
        "key": rule_key,
        "organization": organization,
    }, token)
    rule = rule_data.get("rule", {})
    why_html, how_html = extract_rule_descriptions(rule)
    return html_to_md(why_html), html_to_md(how_html)


# --- Export ------------------------------------------------------------------
def export_results(folder: Path, clean_issue: Dict, why_md: str, how_md: str):
    """Write the three output files and print a summary."""
    written = []
    skipped = []
    for fname, fcontent, flabel in [
        ("where.json", json.dumps(clean_issue, indent=2), "Where is the issue?"),
        ("why.md", why_md, "Why is this an issue?"),
        ("how.md", how_md, "How can I fix it?"),
    ]:
        if write_file(folder, fname, fcontent, flabel):
            written.append(fname)
        else:
            skipped.append(fname)

    if skipped:
        print(f"\nExported {len(written)} file(s) to {folder}/")
        print(f"Skipped {len(skipped)} empty tab(s): {', '.join(skipped)}")
        print("(These tabs don't have content for this issue on SonarCloud.)")
    else:
        print(f"\nAll three tabs exported successfully to {folder}/")


# --- Main --------------------------------------------------------------------
def main():
    token = load_config()
    raw_url = resolve_url()

    component_key, issue_key, pull_request, branch = parse_issue_url(raw_url)
    if not component_key or not issue_key:
        print("ERROR: URL must contain 'id' and 'open' parameters.", file=sys.stderr)
        sys.exit(1)

    print(f"Component : {component_key}")
    print(f"Issue     : {issue_key}")
    if pull_request:
        print(f"PR        : {pull_request}")
    if branch:
        print(f"Branch    : {branch}")

    print("Fetching issue details ...")
    clean_issue = fetch_issue(component_key, issue_key, token, pull_request, branch)
    rule_key = clean_issue.pop("_rule_key")
    organization = clean_issue.pop("_organization")
    issue_message = clean_issue.pop("_message")

    print(f"Fetching rule details for {rule_key} (org: {organization}) ...")
    why_md, how_md = fetch_rule_details(rule_key, organization, token)

    base_name = sanitise_folder_name(issue_message)
    folder = create_unique_folder(base_name)
    print(f"\nOutput folder -> {folder}")

    export_results(folder, clean_issue, why_md, how_md)


if __name__ == "__main__":
    main()
