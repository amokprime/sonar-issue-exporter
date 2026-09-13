"""Tests for sie v1.1.0 CodeQL auto-discovery — repo-wide open alerts.

Covers the new v1.1.0 behavior:
- ``fetch_open_code_scanning_alerts`` — repo-wide open alert fetch via
  ``gh api --paginate``, with silent-drop on any failure (gh missing,
  auth error, network, non-JSON, etc.).
- ``_is_sonar_pushed_alert`` — identify SonarCloud-pushed alerts by
  ``tool.name`` (case-insensitive substring "sonar") so they can be
  dropped (the SonarCloud API already returns them).
- ``_code_scanning_alerts_to_issues`` — convert a list of alerts to the
  sie issue-dict shape, with one rule-metadata entry per distinct rule.
- ``_fetch_code_scanning_for_project`` — the auto-discovery entry point
  called by ``export_url`` after the SonarCloud fetch.
- ``render_combined_markdown`` — the merged Sonar+CodeQL Markdown layout
  with ``## SonarCloud Issues`` and ``## CodeQL Alerts`` sections.
- ``_render_export_markdown`` — the three-way dispatch (both / sonar-only
  / codeql-only / empty).
- ``_run_summary_mode`` CodeQL count inclusion.
- ``export_url`` end-to-end with mocked fetches.

Network-dependent tests (real ``gh api`` calls) are NOT in this file —
the suite stays fast and sandbox-runnable. All ``gh`` invocations are
mocked via ``unittest.mock.patch``.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import sie

# ---------------------------------------------------------------------------
# Test fixtures — minimal alert/issue dict builders
# ---------------------------------------------------------------------------

def _make_codeql_alert(
    *, number=3, rule_id="py/incomplete-url-substring-sanitization",
    path="sie.py", line=42, severity="warning", state="open",
    tool_name="CodeQL", message="Substring check on unparsed URL.",
    help_text="Don't use substring checks on URLs — parse first.",
) -> dict:
    """Build a minimal GitHub code-scanning alert JSON matching the API shape."""
    return {
        "number": number,
        "state": state,
        "rule": {
            "id": rule_id,
            "severity": severity,
            "help": help_text,
        },
        "tool": {"name": tool_name},
        "most_recent_instance": {
            "location": {
                "path": path,
                "start_line": line,
                "end_line": line,
                "start_column": 4,
                "end_column": 10,
            },
            "message": {"text": message},
        },
    }


def _make_sonar_pushed_alert(
    *, number=99, rule_id="python:S3776", path="sie.py", line=128,
) -> dict:
    """Build an alert that looks like SonarCloud pushed it to GH code-scanning."""
    return _make_codeql_alert(
        number=number, rule_id=rule_id, path=path, line=line,
        tool_name="SonarCloud", severity="major",
        message="Refactor this function to reduce its Cognitive Complexity.",
        help_text="Cognitive Complexity measures how hard a function is to read.",
    )


def _make_sonar_issue(
    *, rule="python:S3776", key="AaBprftR68fRE0gxBFjx", line=42,
    component="amokprime_sonar-issue-exporter:sie.py", message="Refactor this.",
    severity="MAJOR", type="CODE_SMELL", status="OPEN",
) -> dict:
    """Build a minimal SonarCloud issue dict matching the API shape."""
    return {
        "rule": rule,
        "component": component,
        "line": line,
        "textRange": {"startLine": line, "endLine": line, "startOffset": 0, "endOffset": 10},
        "message": message,
        "severity": severity,
        "type": type,
        "cleanCodeAttribute": "FOCUSED",
        "cleanCodeAttributeCategory": "ADAPTABLE",
        "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "HIGH"}],
        "flows": [],
        "key": key,
        "status": status,
    }


# ---------------------------------------------------------------------------
# fetch_open_code_scanning_alerts — silent-drop semantics
# ---------------------------------------------------------------------------

class TestFetchOpenCodeScanningAlertsSilentDrop:
    """The fetch must return [] silently on any failure path."""

    def test_returns_empty_when_gh_not_installed(self):
        """If `gh` isn't on PATH, return [] — no exception."""
        with patch("sie.shutil.which", return_value=None):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_on_subprocess_error(self):
        """If `gh api` invocation raises, return [] silently."""
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", side_effect=subprocess.SubprocessError("boom")):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_on_file_not_found(self):
        """FileNotFoundError (gh binary vanished between which() and run()) — silent."""
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", side_effect=FileNotFoundError("no gh")):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_on_nonzero_exit(self):
        """If gh api exits non-zero (auth, rate limit, 404), return [] silently."""
        proc = subprocess.CompletedProcess(
            args=["gh", "api", "x"], returncode=1,
            stdout="", stderr="could not authenticate",
        )
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", return_value=proc):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_on_non_json_output(self):
        """If gh api returns non-JSON, return [] silently."""
        proc = subprocess.CompletedProcess(
            args=["gh", "api", "x"], returncode=0,
            stdout="not json at all", stderr="",
        )
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", return_value=proc):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_on_non_list_json(self):
        """If gh api returns JSON but not a list (e.g. an error object), return []."""
        proc = subprocess.CompletedProcess(
            args=["gh", "api", "x"], returncode=0,
            stdout=json.dumps({"error": "bad request"}), stderr="",
        )
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", return_value=proc):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_empty_list_when_no_alerts(self):
        """If gh api succeeds and returns [], pass it through."""
        proc = subprocess.CompletedProcess(
            args=["gh", "api", "x"], returncode=0,
            stdout="[]", stderr="",
        )
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", return_value=proc):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert result == []

    def test_returns_alerts_on_success(self):
        """If gh api succeeds and returns a list of alerts, return it."""
        alerts = [
            _make_codeql_alert(number=3),
            _make_codeql_alert(number=4, line=99),
        ]
        proc = subprocess.CompletedProcess(
            args=["gh", "api", "x"], returncode=0,
            stdout=json.dumps(alerts), stderr="",
        )
        with patch("sie.shutil.which", return_value="/usr/bin/gh"), \
             patch("sie.subprocess.run", return_value=proc):
            result = sie.fetch_open_code_scanning_alerts("amokprime", "sonar-issue-exporter")
        assert len(result) == 2
        assert result[0]["number"] == 3
        assert result[1]["number"] == 4


# ---------------------------------------------------------------------------
# _is_sonar_pushed_alert — tool.name-based dedup identification
# ---------------------------------------------------------------------------

class TestIsSonarPushedAlert:
    """SonarCloud-pushed alerts are identified by tool.name containing 'sonar'."""

    def test_sonarcloud_tool_name_is_dropped(self):
        alert = _make_sonar_pushed_alert()
        assert sie._is_sonar_pushed_alert(alert) is True

    def test_sonarqube_tool_name_is_dropped(self):
        """Self-hosted SonarQube also pushes via SARIF with tool.name='SonarQube'."""
        alert = _make_codeql_alert(tool_name="SonarQube")
        assert sie._is_sonar_pushed_alert(alert) is True

    def test_codeql_tool_name_is_kept(self):
        alert = _make_codeql_alert(tool_name="CodeQL")
        assert sie._is_sonar_pushed_alert(alert) is False

    def test_case_insensitive_match(self):
        alert = _make_codeql_alert(tool_name="sonarcloud")
        assert sie._is_sonar_pushed_alert(alert) is True

    def test_missing_tool_field_treated_as_native(self):
        """If tool field is absent, assume native (don't drop)."""
        alert = _make_codeql_alert()
        del alert["tool"]
        assert sie._is_sonar_pushed_alert(alert) is False

    def test_missing_name_field_treated_as_native(self):
        """If tool.name is absent, assume native."""
        alert = _make_codeql_alert()
        alert["tool"] = {}
        assert sie._is_sonar_pushed_alert(alert) is False

    def test_other_scanners_kept(self):
        """ESLint, Bandit, Semgrep — all kept (only Sonar-pushed dropped)."""
        for name in ("ESLint", "Bandit", "Semgrep", "CodeQL"):
            alert = _make_codeql_alert(tool_name=name)
            assert sie._is_sonar_pushed_alert(alert) is False


# ---------------------------------------------------------------------------
# _code_scanning_alerts_to_issues — list conversion
# ---------------------------------------------------------------------------

class TestCodeScanningAlertsToIssues:
    def test_converts_single_alert(self):
        alert = _make_codeql_alert(number=3, rule_id="py/foo")
        issues, rules = sie._code_scanning_alerts_to_issues([alert])
        assert len(issues) == 1
        assert issues[0]["key"] == "codeql:3"
        assert issues[0]["rule"] == "py/foo"
        assert issues[0]["component"] == "sie.py"
        assert issues[0]["line"] == 42
        assert "py/foo" in rules
        assert "Don't use substring checks" in rules["py/foo"]["why"]

    def test_converts_multiple_alerts_same_rule(self):
        """Two alerts on the same rule → two issues, one rule metadata entry."""
        a1 = _make_codeql_alert(number=3, rule_id="py/foo", line=10)
        a2 = _make_codeql_alert(number=4, rule_id="py/foo", line=20)
        issues, rules = sie._code_scanning_alerts_to_issues([a1, a2])
        assert len(issues) == 2
        assert len(rules) == 1
        assert "py/foo" in rules

    def test_converts_multiple_alerts_different_rules(self):
        a1 = _make_codeql_alert(number=3, rule_id="py/foo")
        a2 = _make_codeql_alert(number=4, rule_id="py/bar")
        issues, rules = sie._code_scanning_alerts_to_issues([a1, a2])
        assert len(issues) == 2
        assert len(rules) == 2
        assert set(rules.keys()) == {"py/foo", "py/bar"}

    def test_first_alert_wins_rule_metadata(self):
        """When the same rule appears in two alerts, the first alert's help wins."""
        a1 = _make_codeql_alert(
            number=3, rule_id="py/foo", help_text="First help text.",
        )
        a2 = _make_codeql_alert(
            number=4, rule_id="py/foo", help_text="Second help text.",
        )
        _issues, rules = sie._code_scanning_alerts_to_issues([a1, a2])
        assert rules["py/foo"]["why"] == "First help text."

    def test_empty_alert_list_returns_empty(self):
        issues, rules = sie._code_scanning_alerts_to_issues([])
        assert issues == []
        assert rules == {}


# ---------------------------------------------------------------------------
# _fetch_code_scanning_for_project — the auto-discovery entry point
# ---------------------------------------------------------------------------

class TestFetchCodeScanningForProject:
    """The entry point called by export_url after the SonarCloud fetch."""

    def test_returns_empty_when_project_doesnt_split(self):
        """A project key without underscore can't split into owner/repo."""
        with patch("sie.fetch_open_code_scanning_alerts") as mock_fetch:
            result = sie._fetch_code_scanning_for_project("nounderscore")
        assert result == ([], {})
        mock_fetch.assert_not_called()

    def test_returns_empty_when_gh_unavailable(self):
        """If gh is unavailable, fetch_open returns [] — propagate."""
        with patch("sie.fetch_open_code_scanning_alerts", return_value=[]):
            result = sie._fetch_code_scanning_for_project("amokprime_sonar-issue-exporter")
        assert result == ([], {})

    def test_drops_sonar_pushed_alerts(self):
        """SonarCloud-pushed alerts are filtered out before conversion."""
        sonar_alert = _make_sonar_pushed_alert()
        codeql_alert = _make_codeql_alert(number=5)
        with patch(
            "sie.fetch_open_code_scanning_alerts",
            return_value=[sonar_alert, codeql_alert],
        ):
            issues, rules = sie._fetch_code_scanning_for_project(
                "amokprime_sonar-issue-exporter",
            )
        # Only the CodeQL alert remains; the SonarCloud-pushed one is dropped
        assert len(issues) == 1
        assert issues[0]["key"] == "codeql:5"
        assert "py/incomplete-url-substring-sanitization" in rules

    def test_returns_empty_when_all_alerts_are_sonar_pushed(self):
        """If every alert is SonarCloud-pushed, return ([], []) — no CodeQL."""
        sonar_alerts = [_make_sonar_pushed_alert(number=n) for n in range(3)]
        with patch(
            "sie.fetch_open_code_scanning_alerts", return_value=sonar_alerts,
        ):
            issues, rules = sie._fetch_code_scanning_for_project(
                "amokprime_sonar-issue-exporter",
            )
        assert issues == []
        assert rules == {}

    def test_passes_native_alerts_through(self):
        """Native CodeQL alerts (tool.name='CodeQL') are kept and converted."""
        alerts = [
            _make_codeql_alert(number=3, rule_id="py/foo"),
            _make_codeql_alert(number=4, rule_id="py/bar"),
        ]
        with patch(
            "sie.fetch_open_code_scanning_alerts", return_value=alerts,
        ):
            issues, rules = sie._fetch_code_scanning_for_project(
                "amokprime_sonar-issue-exporter",
            )
        assert len(issues) == 2
        assert len(rules) == 2


# ---------------------------------------------------------------------------
# _demote_headings / _strip_project_header — combined-render helpers
# ---------------------------------------------------------------------------

class TestDemoteHeadings:
    def test_demotes_h1_to_h2(self):
        assert sie._demote_headings("# Title") == "## Title"

    def test_demotes_h2_to_h3(self):
        assert sie._demote_headings("## Section") == "### Section"

    def test_demotes_h3_to_h4(self):
        assert sie._demote_headings("### Subsection") == "#### Subsection"

    def test_demotes_all_headings_in_block(self):
        md = "# Title\n\n## Section\n\n### Sub\n\nText"
        out = sie._demote_headings(md, levels=1)
        assert "## Title" in out
        assert "### Section" in out
        assert "#### Sub" in out
        assert "Text" in out  # non-heading line unchanged

    def test_non_heading_lines_unchanged(self):
        """Lines that don't start with # are passed through unchanged."""
        md = "Regular text\n  indented code\n# Heading\nMore text"
        out = sie._demote_headings(md, levels=1)
        assert "Regular text" in out
        assert "  indented code" in out
        assert "## Heading" in out
        assert "More text" in out

    def test_zero_levels_is_noop(self):
        md = "# Title\n## Section"
        assert sie._demote_headings(md, levels=0) == md


class TestStripProjectHeader:
    def test_strips_through_first_hr(self):
        """The header ends at the first `---` line (inclusive)."""
        md = "# Title\n\nGenerated: now\nSource: `x`\n\n---\n\n## Summary\n\nbody"
        out = sie._strip_project_header(md)
        assert out.startswith("## Summary")
        assert "# Title" not in out
        assert "Generated:" not in out
        assert "Source:" not in out

    def test_no_hr_returns_unchanged(self):
        """If there's no `---` in the input, return as-is (defensive)."""
        md = "# Title\n\nbody without hr"
        assert sie._strip_project_header(md) == md

    def test_preserves_focal_issue_after_header(self):
        """If a focal-issue callout follows the header, it's preserved."""
        md = (
            "# Title\n\nGenerated: x\n\n---\n\n"
            "## ★ Focal Issue\n\n- **Key:** `ABC`\n\n---\n\n"
            "## Summary\n\nbody"
        )
        out = sie._strip_project_header(md)
        assert "## ★ Focal Issue" in out
        assert "## Summary" in out
        assert "# Title" not in out


# ---------------------------------------------------------------------------
# render_combined_markdown — the merged Sonar+CodeQL report
# ---------------------------------------------------------------------------

class TestRenderCombinedMarkdown:
    def _make_sonar_render_kwargs(self, issues=None):
        return {
            "source": "test-input",
            "project": "amokprime_sonar-issue-exporter",
            "scope": "main",
            "issues": issues or [_make_sonar_issue()],
            "facets": {},
            "rules": {},
            "token_present": False,
            "focal_key": None,
            "is_local_migration": False,
            "clean": False,
        }

    def _make_codeql_render_kwargs(self, issues=None, rules=None):
        return {
            "source": "test-input",
            "project": "amokprime_sonar-issue-exporter",
            "scope": "code-scanning",
            "issues": issues or [],
            "facets": {},
            "rules": rules or {},
            "token_present": True,
            "focal_key": None,
            "is_local_migration": False,
            "clean": False,
        }

    def test_renders_both_sections_when_both_nonempty(self):
        sonar_issue = _make_sonar_issue(key="sonar-1")
        codeql_issue_dict = sie._code_scanning_alert_to_issue(
            _make_codeql_alert(number=5)
        )
        codeql_rules = {"py/incomplete-url-substring-sanitization": {"why": "x", "how": ""}}
        md = sie.render_combined_markdown(
            source="test", project="amokprime_sonar-issue-exporter", scope="main",
            sonar_issues=[sonar_issue], sonar_facets={}, sonar_rules={},
            codeql_issues=[codeql_issue_dict], codeql_rules=codeql_rules,
            token_present=False, focal_key=None, clean=False,
        )
        assert "# Issues — amokprime_sonar-issue-exporter (main)" in md
        assert "## SonarCloud Issues" in md
        assert "## CodeQL Alerts" in md
        # SonarCloud issue key appears
        assert "sonar-1" in md
        # CodeQL alert key appears
        assert "codeql:5" in md

    def test_renders_only_sonar_section_when_codeql_empty(self):
        """If codeql_issues is empty, the CodeQL Alerts section is omitted."""
        sonar_issue = _make_sonar_issue()
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=[sonar_issue], sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=False,
        )
        assert "## SonarCloud Issues" in md
        assert "## CodeQL Alerts" not in md

    def test_renders_only_codeql_section_when_sonar_empty(self):
        """If sonar_issues is empty, the SonarCloud Issues section is omitted."""
        codeql_issue = sie._code_scanning_alert_to_issue(
            _make_codeql_alert(number=7)
        )
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=[], sonar_facets={}, sonar_rules={},
            codeql_issues=[codeql_issue],
            codeql_rules={"py/foo": {"why": "x", "how": ""}},
            token_present=False, focal_key=None, clean=False,
        )
        assert "## SonarCloud Issues" not in md
        assert "## CodeQL Alerts" in md

    def test_total_line_shows_source_counts(self):
        """The Total line in the header shows per-source counts."""
        sonar_issues = [_make_sonar_issue(key=f"s{i}") for i in range(3)]
        codeql_issues = [
            sie._code_scanning_alert_to_issue(_make_codeql_alert(number=n))
            for n in range(5, 8)
        ]
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=sonar_issues, sonar_facets={}, sonar_rules={},
            codeql_issues=codeql_issues,
            codeql_rules={"py/foo": {"why": "x", "how": ""}},
            token_present=False, focal_key=None, clean=False,
        )
        assert "Total: 6 issue(s) across 2 source(s)" in md
        assert "SonarCloud: 3" in md
        assert "CodeQL: 3" in md

    def test_token_absent_warning_present_without_token(self):
        """Without a token, the warning block is rendered in the combined header."""
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=[_make_sonar_issue()], sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=False,
        )
        assert "No token set" in md

    def test_clean_mode_suppresses_token_warning(self):
        """In clean mode, no token warning — just 'Token: clean'."""
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=[_make_sonar_issue()], sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=True,
        )
        assert "Token: clean" in md
        assert "No token set" not in md

    def test_subsection_headings_are_demoted(self):
        """Under ## SonarCloud Issues, the Summary section becomes ### Summary."""
        md = sie.render_combined_markdown(
            source="test", project="amokprime_test", scope="main",
            sonar_issues=[_make_sonar_issue()], sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=False,
        )
        # The parent heading is ## SonarCloud Issues
        # Under it, the demoted Summary becomes ### Summary (not ## Summary)
        assert "## SonarCloud Issues" in md
        assert "### Summary" in md
        # And per-rule sections become ### Rule: ...
        assert "### Rule:" in md


# ---------------------------------------------------------------------------
# _render_export_markdown — three-way dispatch
# ---------------------------------------------------------------------------

class TestRenderExportMarkdown:
    def test_returns_none_when_both_empty(self):
        """When both sources have no issues, return None (caller skips write)."""
        result = sie._render_export_markdown(
            source="x", project="p", scope="main",
            sonar_issues=[], sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=False,
        )
        assert result is None

    def test_uses_combined_when_both_nonempty(self):
        sonar = [_make_sonar_issue()]
        codeql = [sie._code_scanning_alert_to_issue(_make_codeql_alert())]
        result = sie._render_export_markdown(
            source="x", project="p", scope="main",
            sonar_issues=sonar, sonar_facets={}, sonar_rules={},
            codeql_issues=codeql,
            codeql_rules={"py/foo": {"why": "x", "how": ""}},
            token_present=False, focal_key=None, clean=False,
        )
        assert result is not None
        assert "## SonarCloud Issues" in result
        assert "## CodeQL Alerts" in result

    def test_uses_single_render_when_sonar_only(self):
        """SonarCloud-only path uses render_markdown (no combined header)."""
        sonar = [_make_sonar_issue()]
        result = sie._render_export_markdown(
            source="x", project="p", scope="main",
            sonar_issues=sonar, sonar_facets={}, sonar_rules={},
            codeql_issues=[], codeql_rules={},
            token_present=False, focal_key=None, clean=False,
        )
        assert result is not None
        # Single-source render uses # SonarQube Issues title (not # Issues)
        assert "# SonarQube Issues — p (main)" in result
        # No combined-source sections
        assert "## SonarCloud Issues" not in result
        assert "## CodeQL Alerts" not in result

    def test_uses_single_render_when_codeql_only(self):
        """CodeQL-only path uses render_markdown with scope='code-scanning'."""
        codeql = [sie._code_scanning_alert_to_issue(_make_codeql_alert())]
        result = sie._render_export_markdown(
            source="x", project="p", scope="main",
            sonar_issues=[], sonar_facets={}, sonar_rules={},
            codeql_issues=codeql,
            codeql_rules={"py/foo": {"why": "x", "how": ""}},
            token_present=False, focal_key=None, clean=False,
        )
        assert result is not None
        # CodeQL-only render uses the code-scanning scope display
        assert "GitHub code-scanning" in result


# ---------------------------------------------------------------------------
# export_url — end-to-end with mocked fetches
# ---------------------------------------------------------------------------

class TestExportUrlCodeqlAutoDiscovery:
    """export_url integrates SonarCloud fetch + CodeQL auto-discovery."""

    def _descriptor(self, project="amokprime_sonar-issue-exporter", scope="main"):
        return sie._build_descriptor(project=project, scope=scope)

    def test_both_sources_have_issues_uses_combined_render(self, tmp_path, capsys):
        """Sonar has issues, CodeQL has issues → combined Markdown written."""
        sonar_issues = [_make_sonar_issue(key="sonar-1")]
        codeql_issues = [
            sie._code_scanning_alert_to_issue(_make_codeql_alert(number=5))
        ]
        codeql_rules = {"py/foo": {"why": "x", "how": ""}}
        with self._patch_export_pipeline(
            sonar_issues=sonar_issues, sonar_rules={},
            codeql_issues=codeql_issues, codeql_rules=codeql_rules,
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=str(tmp_path / "out.md"),
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        md = (tmp_path / "out.md").read_text(encoding="utf-8")
        assert "## SonarCloud Issues" in md
        assert "## CodeQL Alerts" in md

    def test_sonar_only_writes_single_render(self, tmp_path):
        """CodeQL empty → SonarCloud-only render (no combined header)."""
        sonar_issues = [_make_sonar_issue()]
        with self._patch_export_pipeline(
            sonar_issues=sonar_issues, sonar_rules={},
            codeql_issues=[], codeql_rules={},
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=str(tmp_path / "out.md"),
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        md = (tmp_path / "out.md").read_text(encoding="utf-8")
        assert "# SonarQube Issues —" in md
        assert "## SonarCloud Issues" not in md
        assert "## CodeQL Alerts" not in md

    def test_codeql_only_writes_codeql_render(self, tmp_path):
        """Sonar empty, CodeQL has alerts → CodeQL-only render."""
        codeql_issues = [
            sie._code_scanning_alert_to_issue(_make_codeql_alert(number=5))
        ]
        codeql_rules = {"py/foo": {"why": "x", "how": ""}}
        with self._patch_export_pipeline(
            sonar_issues=[], sonar_rules={},
            codeql_issues=codeql_issues, codeql_rules=codeql_rules,
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=str(tmp_path / "out.md"),
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        md = (tmp_path / "out.md").read_text(encoding="utf-8")
        assert "GitHub code-scanning" in md
        assert "codeql:5" in md

    def test_both_empty_skips_write(self, tmp_path, capsys):
        """Both sources empty → no file written, message printed, exit 0."""
        with self._patch_export_pipeline(
            sonar_issues=[], sonar_rules={},
            codeql_issues=[], codeql_rules={},
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=str(tmp_path / "out.md"),
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        assert not (tmp_path / "out.md").exists()
        captured = capsys.readouterr()
        assert "No open issues found" in captured.err
        assert "SonarCloud: 0" in captured.err
        assert "CodeQL: 0" in captured.err

    def test_gh_unavailable_silent_drop(self, tmp_path, capsys):
        """If gh is unavailable, CodeQL fetch silently returns [] — no error."""
        sonar_issues = [_make_sonar_issue()]
        # _fetch_code_scanning_for_project is the function that would call gh;
        # we mock it to return ([], {}) — the silent-drop outcome.
        with self._patch_export_pipeline(
            sonar_issues=sonar_issues, sonar_rules={},
            codeql_issues=[], codeql_rules={},
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=str(tmp_path / "out.md"),
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        # File is written (SonarCloud-only path)
        assert (tmp_path / "out.md").exists()
        # Stderr mentions the CodeQL silent-drop
        captured = capsys.readouterr()
        assert "CodeQL: 0 alerts" in captured.err

    def test_default_output_filename_is_issues_md(self, tmp_path):
        """When no explicit output path, the default filename is issues.md."""
        # Make tmp_path look like a git root so _resolve_default_output_dir
        # deterministically returns tmp_path. Without this, the test is
        # environment-dependent: if ~/Downloads exists (common on user
        # machines), _resolve_default_output_dir returns ~/Downloads
        # (the "not in a git project" last-resort path), and the file
        # gets written there instead of tmp_path.
        (tmp_path / ".git").mkdir()
        sonar_issues = [_make_sonar_issue()]
        with self._patch_export_pipeline(
            sonar_issues=sonar_issues, sonar_rules={},
            codeql_issues=[], codeql_rules={},
        ):
            rc = sie.export_url(
                self._descriptor(), output_path=None,
                summary_mode=False, cwd=tmp_path, clean=False,
            )
        assert rc == 0
        assert (tmp_path / "issues.md").exists()

    @staticmethod
    def _patch_export_pipeline(
        *, sonar_issues, sonar_rules, codeql_issues, codeql_rules,
    ):
        """Patch all four export_url fetch points at once.

        Returns a context manager that yields nothing — the caller just
        uses ``with`` to scope the patches. Centralized to keep the
        individual test methods readable (the multi-line ``with``
        statements were pushing past the 100-char line length gate).
        """
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch("sie.get_token", return_value=None))
        stack.enter_context(patch(
            "sie._fetch_with_focal_fallback",
            return_value=(sonar_issues, {}, None),
        ))
        stack.enter_context(patch(
            "sie._fetch_rule_metadata", return_value=sonar_rules,
        ))
        stack.enter_context(patch(
            "sie._fetch_code_scanning_for_project",
            return_value=(codeql_issues, codeql_rules),
        ))
        return stack


# ---------------------------------------------------------------------------
# Summary mode — CodeQL count inclusion
# ---------------------------------------------------------------------------

class TestSummaryModeCodeqlCount:
    """-s / --summary includes a CodeQL alert count line in stdout."""

    def test_summary_includes_codeql_count_line(self, capsys):
        """The summary stdout includes 'CodeQL Alerts: N open'."""
        facets = {
            "severities": [{"val": "MAJOR", "count": 2}],
            "types": [{"val": "CODE_SMELL", "count": 2}],
            "rules": [{"val": "python:S3776", "count": 2}],
        }
        sample_issues = [_make_sonar_issue()]
        sie._print_summary_stdout(
            project="amokprime_test", scope="main", total=2,
            facets=facets, sample_issues=sample_issues,
            codeql_count=3,
        )
        captured = capsys.readouterr()
        assert "CodeQL Alerts: 3 open" in captured.out

    def test_summary_shows_zero_codeql_when_gh_unavailable(self, capsys):
        """If gh is unavailable, the summary shows 'CodeQL Alerts: 0 open'."""
        sie._print_summary_stdout(
            project="amokprime_test", scope="main", total=0,
            facets={}, sample_issues=[], codeql_count=0,
        )
        captured = capsys.readouterr()
        assert "CodeQL Alerts: 0 open" in captured.out

    def test_summary_header_says_sonarcloud(self, capsys):
        """v1.1.0: the header line clarifies 'SonarCloud issue(s)' since
        the total is now source-specific (CodeQL is reported separately)."""
        sie._print_summary_stdout(
            project="p", scope="main", total=5,
            facets={}, sample_issues=[], codeql_count=0,
        )
        captured = capsys.readouterr()
        assert "5 SonarCloud issue(s)" in captured.out

    def test_run_summary_mode_calls_codeql_fetch(self, capsys):
        """_run_summary_mode fetches CodeQL count and passes it to the printer."""
        api_url = "https://sonarcloud.io/api/issues/search?componentKeys=p&issueStatuses=OPEN"
        with patch("sie._api_get", return_value={
            "total": 2, "facets": [], "issues": [_make_sonar_issue()],
        }), patch("sie._fetch_code_scanning_for_project", return_value=([{"x": 1}], {})):
            rc = sie._run_summary_mode(api_url, "p", "main", None, None)
        assert rc == 0
        captured = capsys.readouterr()
        assert "CodeQL Alerts: 1 open" in captured.out


# ---------------------------------------------------------------------------
# Filename rename — DEFAULT_OUTPUT_NAME is issues.md (v1.1.0)
# ---------------------------------------------------------------------------

class TestDefaultOutputFilename:
    """v1.1.0: the default output filename is issues.md, not sonar-issues.md."""

    def test_default_output_name_constant(self):
        assert sie.DEFAULT_OUTPUT_NAME == "issues.md"

    def test_resolve_output_path_uses_issues_md(self, tmp_path):
        """resolve_output_path returns issues.md as the default filename."""
        p = sie.resolve_output_path(explicit=None, base_dir=tmp_path)
        assert p.name == "issues.md"

    def test_resolve_output_path_autoincrements_issues_md(self, tmp_path):
        """If issues.md exists, the next call returns issues1.md."""
        (tmp_path / "issues.md").write_text("existing", encoding="utf-8")
        p = sie.resolve_output_path(explicit=None, base_dir=tmp_path)
        assert p.name == "issues1.md"
