"""Tests for sie.parse_github_url — GitHub URL → SonarCloud descriptor mapping.

Covers:
- /owner/repo → main branch (project key = owner_repo)
- /owner/repo/pull/<N> → ?pullRequest=<N>
- /owner/repo/tree/<branch> → ?branch=<branch>
- /owner/repo/blob/<branch>/... → ?branch=<branch>
- /owner/repo/commit/<sha> → error (SonarCloud doesn't index SHAs)
- .git suffix stripping
- Non-github.com host rejection
- Missing owner/repo rejection
"""

from __future__ import annotations

import pytest

import sie


class TestGithubUrlBasic:
    def test_repo_root_url_maps_to_main(self):
        d = sie.parse_github_url("https://github.com/amokprime/linebyline")
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert "componentKeys=amokprime_linebyline" in d["api_url"]
        # No pullRequest= or branch= in the API URL for main scope
        assert "pullRequest=" not in d["api_url"]
        assert "branch=" not in d["api_url"]

    def test_www_subdomain_accepted(self):
        d = sie.parse_github_url("https://www.github.com/amokprime/linebyline")
        assert d["project"] == "amokprime_linebyline"

    def test_git_suffix_stripped(self):
        d = sie.parse_github_url("https://github.com/amokprime/linebyline.git")
        assert d["project"] == "amokprime_linebyline"

    def test_trailing_slash_handled(self):
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/"
        )
        assert d["project"] == "amokprime_linebyline"


class TestGithubPullRequest:
    def test_pull_url_maps_to_pullRequest_param(self):
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/pull/11"
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "pr:11"
        assert "pullRequest=11" in d["api_url"]

    def test_pull_url_with_trailing_path_ignored(self):
        """GitHub PR URLs sometimes have trailing fragments; we only need /pull/N."""
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/pull/11/files"
        )
        assert d["scope"] == "pr:11"

    def test_non_numeric_pr_raises(self):
        with pytest.raises(ValueError, match="Invalid PR number"):
            sie.parse_github_url(
                "https://github.com/amokprime/linebyline/pull/abc"
            )


class TestGithubBranch:
    def test_tree_url_maps_to_branch_param(self):
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/tree/staging"
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "branch:staging"
        assert "branch=staging" in d["api_url"]

    def test_blob_url_with_branch_and_path(self):
        """blob URLs are /blob/<branch>/<path>... — we extract branch only."""
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/blob/staging/src/main.ts"
        )
        assert d["scope"] == "branch:staging"
        assert "branch=staging" in d["api_url"]

    def test_branch_with_slashes_in_name(self):
        """Some branches have slashes (e.g. feature/foo). GitHub's tree URL
        represents these as /tree/feature/foo — we capture everything after
        /tree/ as the branch name."""
        d = sie.parse_github_url(
            "https://github.com/amokprime/linebyline/tree/feature/sync-rewrite"
        )
        assert d["scope"] == "branch:feature/sync-rewrite"


class TestGithubCommit:
    def test_commit_url_raises_with_helpful_error(self):
        """SonarCloud indexes branches/PRs, not arbitrary commit SHAs."""
        with pytest.raises(ValueError, match="Commit-SHA URLs are not supported"):
            sie.parse_github_url(
                "https://github.com/amokprime/linebyline/commit/abc123"
            )


class TestGithubCodeScanning:
    """GitHub code-scanning alert URLs (/security/code-scanning/<N>).

    These are repo-level alerts (CodeQL etc.), fetched via `gh api` rather
    than the SonarCloud pipeline. The descriptor carries a
    `code_scanning_alert` field so `export_url` routes to the GitHub pipeline.
    """

    def test_code_scanning_url_sets_alert_field(self):
        d = sie.parse_github_url(
            "https://github.com/amokprime/sonar-issue-exporter/security/code-scanning/3"
        )
        assert d["project"] == "amokprime_sonar-issue-exporter"
        assert d["code_scanning_alert"] == 3
        assert d["scope"] == "main"  # repo-level alert, not branch-scoped

    def test_code_scanning_url_preserves_source(self):
        raw = "https://github.com/amokprime/sonar-issue-exporter/security/code-scanning/4"
        d = sie.parse_github_url(raw)
        assert d["source"] == raw

    def test_code_scanning_url_with_www_subdomain(self):
        d = sie.parse_github_url(
            "https://www.github.com/amokprime/sonar-issue-exporter/security/code-scanning/1"
        )
        assert d["code_scanning_alert"] == 1

    def test_invalid_alert_number_raises(self):
        with pytest.raises(ValueError, match="Invalid code-scanning alert number"):
            sie.parse_github_url(
                "https://github.com/amokprime/sonar-issue-exporter/security/code-scanning/abc"
            )


class TestGithubUrlErrors:
    def test_non_github_host_raises(self):
        with pytest.raises(ValueError, match="Not a github.com URL"):
            sie.parse_github_url("https://gitlab.com/amokprime/linebyline")

    def test_missing_owner_repo_raises(self):
        with pytest.raises(ValueError, match="missing owner/repo path"):
            sie.parse_github_url("https://github.com/")