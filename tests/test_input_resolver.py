"""Tests for sie.resolve_input — top-level input dispatch.

Covers:
- None / empty → main branch of CWD's repo (with `discover_repo` mocked)
- SonarCloud URL → parse_url_input
- GitHub URL → parse_github_url
- Fuzzy owner/repo[/branch]
- Single-token shortcuts (pr, main, <branch>) — pr requires `gh` so we
  mock that case
- Local-path sentinel — this branch was REMOVED in the v1.0.0 refactor;
  local-path migration is now gated behind `--migrate`. Verify the
  sentinel is NOT returned for path-like inputs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import sie


class TestResolveUrlInputs:
    def test_sonarcloud_url_dispatches_to_parse_url_input(self):
        d = sie.resolve_input(
            "https://sonarcloud.io/project/issues?id=amokprime_linebyline",
            cwd=Path("/tmp"),
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert d["source"] == "https://sonarcloud.io/project/issues?id=amokprime_linebyline"

    def test_github_url_dispatches_to_parse_github_url(self):
        d = sie.resolve_input(
            "https://github.com/amokprime/linebyline/pull/11",
            cwd=Path("/tmp"),
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "pr:11"

    def test_unsupported_url_host_raises(self):
        with pytest.raises(ValueError, match="Unsupported URL host"):
            sie.resolve_input(
                "https://gitlab.com/amokprime/linebyline",
                cwd=Path("/tmp"),
            )

    def test_url_with_evil_host_embedded_in_path_does_not_bypass_dispatch(self):
        """CodeQL py/incomplete-url-substring-sanitization regression test.

        A URL like `https://evil-example.net/sonarcloud.io` would have passed
        the old substring check (`"sonarcloud.io" in raw`), but urlparse
        correctly identifies the host as `evil-example.net`, so it falls
        through to the unsupported-host error.
        """
        with pytest.raises(ValueError, match="Unsupported URL host"):
            sie.resolve_input(
                "https://evil-example.net/sonarcloud.io",
                cwd=Path("/tmp"),
            )

    def test_url_with_github_in_path_does_not_bypass_dispatch(self):
        """Same CodeQL fix for the github.com branch of the dispatch."""
        with pytest.raises(ValueError, match="Unsupported URL host"):
            sie.resolve_input(
                "https://evil-example.net/github.com/amokprime/linebyline",
                cwd=Path("/tmp"),
            )


class TestResolveFuzzyOwnerRepo:
    def test_owner_repo_maps_to_main(self):
        d = sie.resolve_input("amokprime/linebyline", cwd=Path("/tmp"))
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert d["source"] == "amokprime/linebyline"

    def test_owner_repo_branch_maps_to_branch_scope(self):
        d = sie.resolve_input(
            "amokprime/linebyline/staging", cwd=Path("/tmp"),
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "branch:staging"
        assert "branch=staging" in d["api_url"]


class TestResolveSingleToken:
    """Single-token shortcuts need CWD's repo. We mock discover_repo to
    avoid depending on the test machine's filesystem layout."""

    @patch("sie.discover_repo")
    def test_main_token_resolves_to_main_branch(self, mock_discover):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        d = sie.resolve_input("main", cwd=Path("/fake"))
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert d["source"] == "main"

    @patch("sie.discover_repo")
    def test_branch_name_token_resolves_to_branch_scope(self, mock_discover):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        d = sie.resolve_input("staging", cwd=Path("/fake"))
        assert d["scope"] == "branch:staging"
        assert "branch=staging" in d["api_url"]

    @patch("sie.discover_repo")
    def test_pr_token_invokes_gh(self, mock_discover):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        # Mock the gh subprocess to return PR #42
        with patch("sie._resolve_most_recent_pr") as mock_pr:
            mock_pr.return_value = sie._build_descriptor(
                project="amokprime_linebyline", scope="pr:42",
                pull_request=42,
            )
            d = sie.resolve_input("pr", cwd=Path("/fake"))
            assert d["scope"] == "pr:42"
            assert "pullRequest=42" in d["api_url"]
            mock_pr.assert_called_once()

    @patch("sie.discover_repo")
    def test_pr_token_without_gh_raises_helpful_error(self, mock_discover):
        """If `gh` is not installed, the pr shortcut must give an actionable
        error pointing to install URL — not a stack trace."""
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        # Force `gh` to be absent
        with patch("sie.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="requires the GitHub CLI"):
                sie.resolve_input("pr", cwd=Path("/fake"))


class TestResolveEmptyInput:
    @patch("sie.discover_repo")
    def test_none_input_uses_cwd_repo_main(self, mock_discover):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        d = sie.resolve_input(None, cwd=Path("/fake"))
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        # Source line documents the no-arg + CWD resolution
        assert "no arg" in d["source"].lower()
        assert "amokprime/linebyline" in d["source"]

    @patch("sie.discover_repo")
    def test_empty_string_input_treated_as_none(self, mock_discover):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        d = sie.resolve_input("", cwd=Path("/fake"))
        assert d["scope"] == "main"


class TestLocalPathSentinelRemoved:
    """CRITICAL: the local-path sentinel was REMOVED from resolve_input in
    the v1.0.0 disambiguation refactor. Local-path migration is now
    gated behind --migrate in main(). Verify path-like inputs are NOT
    caught by resolve_input — they should raise (forcing the CLI layer
    to handle them as output paths or --migrate)."""

    def test_absolute_path_raises_value_error(self):
        """resolve_input should NOT handle /abs/paths — those belong to
        the CLI disambiguation layer. This confirms the refactor is intact."""
        with pytest.raises((ValueError, RuntimeError)):
            sie.resolve_input("/tmp/some-folder", cwd=Path("/tmp"))

    def test_home_relative_path_raises_value_error(self):
        with pytest.raises((ValueError, RuntimeError)):
            sie.resolve_input("~/some-folder", cwd=Path("/tmp"))

    def test_dot_slash_path_raises_value_error(self):
        with pytest.raises((ValueError, RuntimeError)):
            sie.resolve_input("./some-folder", cwd=Path("/tmp"))