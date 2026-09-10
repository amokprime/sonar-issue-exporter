"""Tests for sie.render_markdown — Markdown report shape.

Tests verify the structure of the rendered Markdown, not the exact text.
Covered:
- Header (title, source, total, token line)
- Focal Issue callout (only when ?open=<KEY> was in the URL)
- Summary table (severity counts + type counts side-by-side)
- Per-rule sections (Why / How to fix / Instances table)
- local: prefix on synthetic keys
- Token-absent placeholder for why/how
"""

from __future__ import annotations

import sie


def _make_issue(
    *, rule="python:S3776", key="AaBprftR68fRE0gxBFjx", line=42,
    component="amokprime_linebyline:src/main.ts", message="Refactor this.",
    severity="MAJOR", type="CODE_SMELL", status="OPEN",
    clean_code="FORMATTED", clean_code_cat="CONSISTENT",
) -> dict:
    """Build a minimal issue dict matching the SonarCloud API shape."""
    return {
        "rule": rule,
        "component": component,
        "line": line,
        "textRange": {"startLine": line, "endLine": line, "startOffset": 0, "endOffset": 10},
        "message": message,
        "severity": severity,
        "type": type,
        "cleanCodeAttribute": clean_code,
        "cleanCodeAttributeCategory": clean_code_cat,
        "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "HIGH"}],
        "flows": [],
        "key": key,
        "status": status,
    }


class TestRenderHeader:
    def test_title_includes_project_and_scope(self):
        md = sie.render_markdown(
            source="test-input",
            project="amokprime_linebyline",
            scope="main",
            issues=[],
            facets={},
            rules={},
            token_present=False,
            focal_key=None,
        )
        assert "# SonarQube Issues — amokprime_linebyline (main)" in md

    def test_pr_scope_displayed_as_pr_n(self):
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="pr:11",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "PR #11" in md

    def test_branch_scope_displayed_with_backticks(self):
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="branch:staging",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "branch `staging`" in md

    def test_total_count_in_header(self):
        issues = [_make_issue(), _make_issue(key="K2")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "2 issue(s)" in md

    def test_source_line_in_header(self):
        md = sie.render_markdown(
            source="https://github.com/amokprime/linebyline/pull/11",
            project="amokprime_linebyline", scope="pr:11",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "Source: `https://github.com/amokprime/linebyline/pull/11`" in md


class TestRenderTokenWarning:
    def test_token_absent_warning_rendered(self):
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "SONAR_TOKEN" in md
        assert "No token set" in md

    def test_token_present_no_warning(self):
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[], facets={}, rules={},
            token_present=True, focal_key=None,
        )
        assert "No token set" not in md
        assert "Token: present" in md

    def test_local_migration_suppresses_token_warning(self):
        """Local-folder migration always has why/how on disk, so the token
        warning should NOT appear (regardless of token_present)."""
        md = sie.render_markdown(
            source="/path/to/folder", project="amokprime_linebyline",
            scope="local-export",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
            is_local_migration=True,
        )
        assert "No token set" not in md
        assert "Token:" not in md


class TestRenderFocalIssue:
    def test_focal_callout_rendered_when_focal_key_set(self):
        issue = _make_issue(key="AaBprftR68fRE0gxBFjx", line=42)
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key="AaBprftR68fRE0gxBFjx",
        )
        assert "## ★ Focal Issue" in md
        assert "AaBprftR68fRE0gxBFjx" in md
        assert "src/main.ts:42" in md  # file:line rendered

    def test_focal_callout_not_rendered_when_focal_key_none(self):
        issue = _make_issue()
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "★ Focal Issue" not in md

    def test_focal_issue_star_in_instances_table(self):
        """The focal issue should be marked with a ★ in its rule's instances table."""
        issue = _make_issue(key="AaBprftR68fRE0gxBFjx", line=42)
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key="AaBprftR68fRE0gxBFjx",
        )
        # The instances table row for the focal issue has the ★ inside the
        # backticks (renderer does `f"`{star}{comp}`"`), so the cell looks
        # like: | `★ src/main.ts` | L42 | ... | — star + filename both
        # inside a single pair of backticks.
        assert "`★ src/main.ts`" in md

    def test_focal_callout_deep_link(self):
        issue = _make_issue(key="AaBprftR68fRE0gxBFjx")
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key="AaBprftR68fRE0gxBFjx",
        )
        # Deep link format: https://sonarcloud.io/project/issues?open=KEY&id=PROJECT
        assert (
            "https://sonarcloud.io/project/issues?"
            "open=AaBprftR68fRE0gxBFjx&id=amokprime_linebyline"
        ) in md


class TestRenderSummaryTable:
    def test_severity_counts_in_table(self):
        issues = [
            _make_issue(key="A", severity="CRITICAL"),
            _make_issue(key="B", severity="CRITICAL"),
            _make_issue(key="C", severity="MAJOR"),
            _make_issue(key="D", severity="MINOR"),
        ]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        # Severity table headers present
        assert "| Severity" in md
        assert "| Count |" in md
        # Counts in the rendered table (computed from issues when facets empty)
        assert "CRITICAL" in md
        assert "MAJOR" in md

    def test_type_counts_in_summary_table(self):
        issues = [
            _make_issue(key="A", type="CODE_SMELL"),
            _make_issue(key="B", type="BUG"),
        ]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "CODE_SMELL" in md
        assert "BUG" in md

    def test_top_rules_listed(self):
        issues = [
            _make_issue(key="A", rule="javascript:S2681"),
            _make_issue(key="B", rule="javascript:S2681"),
            _make_issue(key="C", rule="javascript:S2681"),
            _make_issue(key="D", rule="Web:S6819"),
        ]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "javascript:S2681" in md
        assert "3×" in md


class TestRenderPerRuleSection:
    def test_rule_section_header(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "## Rule: `python:S3776`" in md

    def test_why_section_placeholder_when_no_token(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "### Why" in md
        # Placeholder text points to SONAR_API_KEY (preferred) or SONAR_TOKEN
        assert "SONAR_API_KEY" in md or "SONAR_TOKEN" in md

    def test_why_section_renders_content_when_present(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={
                "python:S3776": {
                    "why": "Cognitive Complexity measures how hard a function is to read.",
                    "how": "Extract helpers and use early returns.",
                },
            },
            token_present=True, focal_key=None,
        )
        assert "Cognitive Complexity measures how hard" in md
        assert "Extract helpers and use early returns" in md

    def test_how_section_placeholder_when_no_token(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "### How to fix" in md

    def test_instances_table_includes_file_line_message_key_status(self):
        issue = _make_issue(
            key="AaBprftR68fRE0gxBFjx", line=42,
            component="amokprime_linebyline:src/main.ts",
            message="Refactor this function.",
        )
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        # All key columns appear
        assert "src/main.ts" in md
        assert "L42" in md
        assert "Refactor this function." in md
        assert "AaBprftR68fRE0gxBFjx" in md
        assert "OPEN" in md

    def test_lunknown_for_null_line(self):
        """Issues with line: null should render Lunknown in the table."""
        issue = _make_issue(line=None)
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        assert "Lunknown" in md

    def test_local_prefix_on_synthetic_keys_suppressed_in_deep_links(self):
        """When an issue key starts with `local:`, deep-link generation
        should be suppressed (clicking would 404 on SonarCloud)."""
        issue = _make_issue(key="local:folder/L42")
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={}, rules={},
            token_present=False, focal_key=None,
        )
        # The instances table still shows the synthetic key
        assert "local:folder/L42" in md
        # But the deep-links line should NOT contain this key
        # (it should use the generic <KEY> placeholder)
        assert "open=local:folder/L42" not in md


class TestRenderRuleSortOrder:
    def test_critical_rules_sort_before_major(self):
        """Rules are sorted worst-severity-first so the worst issues appear
        at the top of the report."""
        critical = _make_issue(
            rule="python:S3776", key="A", severity="CRITICAL",
        )
        major = _make_issue(
            rule="javascript:S2681", key="B", severity="MAJOR",
        )
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[major, critical],  # passed in reverse order
            facets={}, rules={},
            token_present=False, focal_key=None,
        )
        # CRITICAL rule should appear before MAJOR rule in the rendered Markdown
        critical_pos = md.index("## Rule: `python:S3776`")
        major_pos = md.index("## Rule: `javascript:S2681`")
        assert critical_pos < major_pos


class TestRenderCleanMode:
    """Tests for the -c/--clean flag: silently drop Why/How sections.

    When clean=True, the Why and How subsections are omitted entirely (no
    placeholder, no warning). This avoids pushing possibly-licensed Sonar
    content to a chat. The Instances table is still rendered (issue data
    is the user's own project's scan results).
    """

    def test_clean_drops_why_section(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={},
            rules={"python:S3776": {"why": "Licensed Sonar content", "how": ""}},
            token_present=True, focal_key=None,
            clean=True,
        )
        assert "### Why" not in md
        assert "Licensed Sonar content" not in md

    def test_clean_drops_how_section(self):
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=issues, facets={},
            rules={"python:S3776": {"why": "", "how": "Licensed fix guidance"}},
            token_present=True, focal_key=None,
            clean=True,
        )
        assert "### How to fix" not in md
        assert "Licensed fix guidance" not in md

    def test_clean_keeps_instances_table(self):
        """The Instances table is safe (user's own scan data, not licensed)."""
        issue = _make_issue(rule="python:S3776", key="ABC123", line=42)
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[issue], facets={},
            rules={"python:S3776": {"why": "Licensed", "how": "Licensed"}},
            token_present=True, focal_key=None,
            clean=True,
        )
        assert "### Instances" in md
        assert "L42" in md
        assert "ABC123" in md

    def test_clean_header_shows_clean_status(self):
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[], facets={}, rules={},
            token_present=True, focal_key=None,
            clean=True,
        )
        assert "Token: clean" in md
        # No token-absent warning in clean mode
        assert "No token set" not in md

    def test_clean_no_warning_block(self):
        """Clean mode should not render the 'No token set' warning block,
        even when token_present is False."""
        md = sie.render_markdown(
            source="x", project="amokprime_linebyline", scope="main",
            issues=[], facets={}, rules={},
            token_present=False, focal_key=None,
            clean=True,
        )
        assert "No token set" not in md
        assert "SONAR_API_KEY" not in md

    def test_clean_does_not_affect_local_migration(self):
        """Clean mode is irrelevant for local migration (why/how come from
        disk, not licensed API). But if passed, it should still suppress
        the sections consistently."""
        issues = [_make_issue(rule="python:S3776")]
        md = sie.render_markdown(
            source="/path/to/folder", project="amokprime_linebyline",
            scope="local-export",
            issues=issues, facets={},
            rules={"python:S3776": {"why": "from disk", "how": "from disk"}},
            token_present=True, focal_key=None,
            is_local_migration=True,
            clean=True,
        )
        assert "### Why" not in md
        assert "### How to fix" not in md
        assert "from disk" not in md
