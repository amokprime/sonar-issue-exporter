#!/usr/bin/env python3
"""
Export all three tabs of a SonarCloud issue from a browser URL.

Reads BEARER_TOKEN and RAW_URL from .env (or environment variables).
For each run, creates a subfolder named after the issue’s message, then saves:
  - where.json  (the stripped-down issue data)
  - why.md      (the "Why is this an issue?" explanation)
  - how.md      (the "How can I fix it?" guidance)

Files for tabs that have no content on SonarCloud are skipped (not written)
instead of being created as empty 0 KB files. A message explains which tabs
were skipped and why.

Duplicate issue names get a counter suffix (e.g. "issue_name", "issue_name_1", …).
"""

import os
import sys
import json
import re
import html as html_mod
import requests
from pathlib import Path
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

load_env(Path(__file__).parent / ".env")

TOKEN = os.getenv("BEARER_TOKEN")

# --- Parse URL (from command line, env, or .env) ----------------------------
RAW_URL = None

if len(sys.argv) > 1:
    RAW_URL = sys.argv[1]                     # take URL as first argument
else:
    RAW_URL = os.getenv("RAW_URL")            # fallback to environment
    if not RAW_URL:
        # final fallback: .env file
        load_env(Path(__file__).parent / ".env")
        RAW_URL = os.getenv("RAW_URL")


# --- Parse the URL -----------------------------------------------------------
parsed = urlparse(RAW_URL)
qs = parse_qs(parsed.query)

component_key = qs.get("id", [None])[0]
issue_key     = qs.get("open", [None])[0]
pull_request  = qs.get("pullRequest", [None])[0]   # e.g. "5"
branch        = qs.get("branch", [None])[0]         # e.g. "feature/foo"

if not component_key or not issue_key:
    print("ERROR: URL must contain 'id' and 'open' parameters.", file=sys.stderr)
    sys.exit(1)

print(f"Component : {component_key}")
print(f"Issue     : {issue_key}")
if pull_request:
    print(f"PR        : {pull_request}")
if branch:
    print(f"Branch    : {branch}")


# --- Helper: API call --------------------------------------------------------
BASE = "https://sonarcloud.io/api"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

def api_get(endpoint: str, params: dict) -> dict:
    url = f"{BASE}/{endpoint}"
    resp = requests.get(url, params=params, headers=HEADERS)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"\nAPI ERROR: {e}", file=sys.stderr)
        print("Response body:", resp.text, file=sys.stderr)
        raise
    return resp.json()


# --- 1. "Where" - fetch the issue and clean it -------------------------------
print("Fetching issue details ...")
# Build API params — include pullRequest/branch if present in the URL
# (SonarCloud only returns main-branch issues by default; PR-only issues
# are invisible unless you explicitly scope the search.)
search_params = {
    "issues": issue_key,
    "componentKeys": component_key,
}
if pull_request:
    search_params["pullRequest"] = pull_request
if branch:
    search_params["branch"] = branch

issue_data = api_get("issues/search", search_params)
issues = issue_data.get("issues", [])
if not issues:
    print("ERROR: issue not found.", file=sys.stderr)
    sys.exit(1)

issue = issues[0]
rule_key = issue.get("rule")
organization = issue.get("organization")   # Required by rules/show
issue_message = issue.get("message", "unknown_issue")

if not rule_key:
    print("ERROR: rule key missing from issue.", file=sys.stderr)
    sys.exit(1)

# Clean the issue (keep only diagnostic fields)
KEEP_FIELDS = {
    "rule", "severity", "type", "component", "line", "textRange",
    "message", "flows", "impacts", "cleanCodeAttribute", "cleanCodeAttributeCategory"
}
clean_issue = {k: issue[k] for k in KEEP_FIELDS if k in issue}


# --- 2. "Why" and "How" - fetch rule details ---------------------------------
print(f"Fetching rule details for {rule_key} (org: {organization}) ...")
rule_data = api_get("rules/show", {
    "key": rule_key,
    "organization": organization,
})
rule = rule_data.get("rule", {})

# SonarCloud now structures rule descriptions into sections that match the UI tabs.
sections = {s["key"]: s["content"] for s in rule.get("descriptionSections", [])}

if sections:
    # "Why is this an issue?" tab = introduction + root_cause
    intro = sections.get("introduction", "")
    root  = sections.get("root_cause", "")
    why_html = f"{intro}\n\n{root}".strip()

    # "How can I fix it?" tab = how_to_fix
    how_html = sections.get("how_to_fix", "")

    # If neither introduction nor root_cause exist, fall back to htmlDesc/mdDesc
    if not why_html:
        why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
else:
    # Fallback for older rules that only have a single htmlDesc / mdDesc field
    why_html = rule.get("htmlDesc") or rule.get("mdDesc") or ""
    how_html = ""

# Convert HTML to Markdown
why_md = html_to_md(why_html)
how_md = html_to_md(how_html)


# --- 3. Create a sanitised output folder named after the issue message -------
def sanitise_folder_name(raw: str, max_len: int = 80) -> str:
    """
    Convert an issue message into a folder-safe name.
    - Replace spaces with underscores
    - Remove characters illegal on Windows/macOS/Linux
    - Collapse multiple underscores
    - Truncate to max_len
    """
    # Replace spaces first so we don't turn them into underscores later
    name = raw.replace(' ', '_')
    # Remove characters not allowed in folder names (cross-platform)
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Strip leading/trailing dots (Windows doesn't like them) and hyphens/spaces
    name = name.strip(' .-')
    # Truncate
    if len(name) > max_len:
        name = name[:max_len].rstrip('_')
    # Fallback to a safe default if empty
    return name or "issue"

base_name = sanitise_folder_name(issue_message)
folder = Path(base_name)

# If folder exists, append _1, _2, …
counter = 1
while folder.exists():
    folder = Path(f"{base_name}_{counter}")
    counter += 1

folder.mkdir(parents=True, exist_ok=False)
print(f"\nOutput folder → {folder}")

# Write files inside the new folder — skip empty files with a clear message
def write_file(filename: str, content: str, tab_label: str = ""):
    """Write content to file. Skip if content is empty/whitespace-only."""
    if not content or not content.strip():
        label = f' "{tab_label}" tab' if tab_label else ''
        print(f"  Skipped → {filename} (no content available for{label} on SonarCloud)")
        return False
    filepath = folder / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Saved → {filepath}")
    return True

written = []
skipped = []
for fname, fcontent, flabel in [
    ("where.json", json.dumps(clean_issue, indent=2), "Where is the issue?"),
    ("why.md", why_md, "Why is this an issue?"),
    ("how.md", how_md, "How can I fix it?"),
]:
    if write_file(fname, fcontent, flabel):
        written.append(fname)
    else:
        skipped.append(fname)

if skipped:
    print(f"\nExported {len(written)} file(s) to {folder}/")
    print(f"Skipped {len(skipped)} empty tab(s): {', '.join(skipped)}")
    print("(These tabs don't have content for this issue on SonarCloud.)")
else:
    print(f"\nAll three tabs exported successfully to {folder}/")