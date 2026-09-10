"""Tests for sie.parse_url_input — SonarCloud API/UI URL parsing.

Covers:
- API URL passthrough + ps=500 normalization
- UI URL → API URL conversion (id= -> componentKeys=)
- UI URL with extra params (sinceLeakPeriod, issueStatuses=OPEN,CONFIRMED) —
  these must be preserved through the conversion, not dropped.
- ?open=<KEY> focal-issue extraction
- branch= and pullRequest= scoping
- Error cases (missing id, unrecognized path, non-sonarcloud host)
"""

from __future__ import annotations

import pytest

import sie


# --- API URLs ---------------------------------------------------------------

class TestApiUrlParsing:
    def test_api_url_passes_through_with_ps_normalization(self):
        """API URLs are passed through; ps=500 is forced for efficient pagination."""
        d = sie.parse_url_input(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=amokprime_linebyline&issueStatuses=OPEN"
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert d["focal_key"] is None
        # ps=500 must be in the API URL
        assert "ps=500" in d["api_url"]
        assert "issueStatuses=OPEN" in d["api_url"]

    def test_api_url_preserves_pull_request_scope(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=amokprime_linebyline&pullRequest=11"
        )
        assert d["scope"] == "pr:11"

    def test_api_url_preserves_branch_scope(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=amokprime_linebyline&branch=staging"
        )
        assert d["scope"] == "branch:staging"

    def test_api_url_extracts_issues_param_as_focal_key(self):
        """The ?issues=<KEY> API param is treated as the focal-issue key."""
        d = sie.parse_url_input(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=amokprime_linebyline&issues=AaBprftR68fRE0gxBFjx"
        )
        assert d["focal_key"] == "AaBprftR68fRE0gxBFjx"

    def test_api_url_defaults_issue_statuses_to_open(self):
        """If issueStatuses is missing, default to OPEN."""
        d = sie.parse_url_input(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=amokprime_linebyline"
        )
        assert "issueStatuses=OPEN" in d["api_url"]


# --- UI URLs ---------------------------------------------------------------

class TestUiUrlParsing:
    def test_basic_ui_url_converts_to_api(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?id=amokprime_linebyline"
        )
        assert d["project"] == "amokprime_linebyline"
        assert d["scope"] == "main"
        assert d["focal_key"] is None
        # UI's ?id= becomes API's ?componentKeys=
        assert "componentKeys=amokprime_linebyline" in d["api_url"]
        # The ?id= param must be removed (it's not a valid API param)
        assert "id=amokprime_linebyline" not in d["api_url"]

    def test_ui_url_extracts_open_param_as_focal_key(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?"
            "open=AaBprftR68fRE0gxBFjx&id=amokprime_linebyline"
        )
        assert d["focal_key"] == "AaBprftR68fRE0gxBFjx"
        # ?open= must be removed from the API URL (not a valid API param)
        assert "open=" not in d["api_url"]

    def test_ui_url_with_pull_request(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?"
            "id=amokprime_linebyline&pullRequest=11"
        )
        assert d["scope"] == "pr:11"
        assert "pullRequest=11" in d["api_url"]

    def test_ui_url_with_branch(self):
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?"
            "id=amokprime_linebyline&branch=staging"
        )
        assert d["scope"] == "branch:staging"
        assert "branch=staging" in d["api_url"]

    def test_ui_url_preserves_extra_params(self):
        """Extra UI params like sinceLeakPeriod and issueStatuses must pass through.

        This is the case the user explicitly called out in the v1.0.0 spec:
          sie 'https://sonarcloud.io/project/issues?id=...&issueStatuses=OPEN,CONFIRMED&sinceLeakPeriod=true'
        """
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?"
            "id=amokprime_linebyline&pullRequest=11"
            "&issueStatuses=OPEN,CONFIRMED&sinceLeakPeriod=true"
        )
        assert d["scope"] == "pr:11"
        assert "issueStatuses=OPEN,CONFIRMED" in d["api_url"]
        assert "sinceLeakPeriod=true" in d["api_url"]
        assert "pullRequest=11" in d["api_url"]

    def test_ui_url_with_user_provided_issue_statuses_not_overwritten(self):
        """If the user passed issueStatuses explicitly, don't default to OPEN."""
        d = sie.parse_url_input(
            "https://sonarcloud.io/project/issues?"
            "id=amokprime_linebyline&issueStatuses=OPEN,CONFIRMED"
        )
        # User's value wins
        assert "issueStatuses=OPEN,CONFIRMED" in d["api_url"]
        # OPEN-only default is NOT applied
        assert "issueStatuses=OPEN&" not in d["api_url"]


# --- Error cases -----------------------------------------------------------

class TestUrlParsingErrors:
    def test_non_sonarcloud_host_raises(self):
        with pytest.raises(ValueError, match="Not a sonarcloud.io URL"):
            sie.parse_url_input("https://example.com/issues?id=foo")

    def test_ui_url_missing_id_raises(self):
        with pytest.raises(ValueError, match=r"missing \?id=<PROJECT> param"):
            sie.parse_url_input(
                "https://sonarcloud.io/project/issues?open=KEY"
            )

    def test_unrecognized_path_raises(self):
        with pytest.raises(ValueError, match="Unrecognized SonarCloud URL path"):
            sie.parse_url_input(
                "https://sonarcloud.io/some/other/path?id=foo"
            )

    def test_www_subdomain_accepted(self):
        """www.sonarcloud.io should be treated the same as sonarcloud.io."""
        d = sie.parse_url_input(
            "https://www.sonarcloud.io/project/issues?id=amokprime_linebyline"
        )
        assert d["project"] == "amokprime_linebyline"