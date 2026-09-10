"""Tests for sie's output path resolution and migration auto-discovery.

Covers:
- ``_find_git_root`` — walk up to find .git
- ``_resolve_default_output_dir`` — scratch/ → cwd (git root) → cwd (git
  non-root) → ~/Downloads (last resort)
- ``_looks_like_issues_folder`` — heuristic for 0.2.x export folder shape
- ``_discover_migrate_folder`` — auto-discovery of issues/ subfolder or
  cwd-as-issues-folder, with safety refusals at git root and on clobber
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import sie


class TestFindGitRoot:
    def test_returns_cwd_when_dot_git_exists(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        assert sie._find_git_root(tmp_path) == tmp_path.resolve()

    def test_walks_up_to_find_dot_git(self, tmp_path: Path):
        """If CWD is deep inside a repo, _find_git_root walks up to the root."""
        git_root = tmp_path / "repo"
        (git_root / ".git").mkdir(parents=True)
        deep = git_root / "archive" / "0.2.0" / "issues"
        deep.mkdir(parents=True)
        assert sie._find_git_root(deep) == git_root.resolve()

    def test_returns_none_when_not_in_git_repo(self, tmp_path: Path):
        """No .git anywhere up the tree → None."""
        # tmp_path itself has no .git, and we assume /tmp isn't a git repo
        assert sie._find_git_root(tmp_path) is None or \
            sie._find_git_root(tmp_path) != tmp_path  # /tmp might be in a repo

    def test_dot_git_file_also_detected(self, tmp_path: Path):
        """Submodules use a .git file (not dir) — _find_git_root should
        detect that too via .exists()."""
        (tmp_path / ".git").write_text("gitdir: ../.git/modules/sub")
        assert sie._find_git_root(tmp_path) == tmp_path.resolve()


class TestResolveDefaultOutputDir:
    def test_at_git_root_with_scratch_uses_scratch(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "scratch").mkdir()
        result = sie._resolve_default_output_dir(tmp_path)
        assert result == tmp_path / "scratch"

    def test_at_git_root_without_scratch_uses_cwd(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        result = sie._resolve_default_output_dir(tmp_path)
        assert result == tmp_path

    def test_inside_git_project_not_root_uses_cwd(self, tmp_path: Path):
        git_root = tmp_path / "repo"
        (git_root / ".git").mkdir(parents=True)
        deep = git_root / "archive" / "0.2.0"
        deep.mkdir(parents=True)
        result = sie._resolve_default_output_dir(deep)
        assert result == deep

    @patch("sie.LAST_RESORT_OUTPUT_DIR")
    def test_not_in_git_project_uses_downloads_last_resort(
        self, mock_downloads, tmp_path: Path,
    ):
        """Not in a git project → ~/Downloads (last resort)."""
        # Make ~/Downloads appear to exist
        mock_downloads.is_dir.return_value = True
        mock_downloads.__str__ = lambda self: "/fake/home/Downloads"
        # tmp_path has no .git and we mock its parent chain to not have .git
        # by patching _find_git_root
        with patch("sie._find_git_root", return_value=None):
            result = sie._resolve_default_output_dir(tmp_path)
        assert result == mock_downloads


class TestLooksLikeIssuesFolder:
    def test_true_when_subdir_has_l_json(self, tmp_path: Path):
        issues = tmp_path / "issues"
        cat = issues / "Some_rule_category"
        cat.mkdir(parents=True)
        (cat / "L42.json").write_text("{}", encoding="utf-8")
        assert sie._looks_like_issues_folder(issues) is True

    def test_true_when_lunknown_json_present(self, tmp_path: Path):
        """Lunknown.json (closed-issue marker) should also match."""
        issues = tmp_path / "issues"
        cat = issues / "Closed_category"
        cat.mkdir(parents=True)
        (cat / "Lunknown.json").write_text("{}", encoding="utf-8")
        assert sie._looks_like_issues_folder(issues) is True

    def test_false_when_no_l_json_files(self, tmp_path: Path):
        issues = tmp_path / "issues"
        cat = issues / "category"
        cat.mkdir(parents=True)
        (cat / "README.md").write_text("not an issue", encoding="utf-8")
        assert sie._looks_like_issues_folder(issues) is False

    def test_false_when_empty(self, tmp_path: Path):
        issues = tmp_path / "issues"
        issues.mkdir()
        assert sie._looks_like_issues_folder(issues) is False

    def test_false_when_not_a_dir(self, tmp_path: Path):
        assert sie._looks_like_issues_folder(tmp_path / "nonexistent") is False


class TestDiscoverMigrateFolder:
    """Tests for sie._discover_migrate_folder — auto-discovery of the
    issues/ folder to migrate.

    Two cases (per user spec):
      1. CWD contains an issues/ subfolder → migrate that, output to CWD
      2. CWD itself is an issues folder → migrate CWD, output to parent

    Safety refusals:
      - .git/ in CWD (auto-discovery at git root is too risky)
      - sonar-issues.md already exists in the output dir (don't clobber)
    """

    def _build_issues_folder(self, parent: Path) -> Path:
        """Build a minimal issues/ folder under parent with one L*.json."""
        issues = parent / "issues"
        cat = issues / "Some_category"
        cat.mkdir(parents=True)
        (cat / "L42.json").write_text(json.dumps({
            "rule": "python:S3776",
            "component": "test:file.py",
            "line": 42,
            "message": "test issue",
            "severity": "MAJOR",
            "type": "CODE_SMELL",
            "cleanCodeAttribute": "FOCUSED",
            "cleanCodeAttributeCategory": "ADAPTABLE",
            "impacts": [],
            "flows": [],
        }), encoding="utf-8")
        return issues

    def test_case1_cwd_contains_issues_subfolder(self, tmp_path: Path):
        """CWD has an issues/ subfolder → migrate that, output to CWD."""
        self._build_issues_folder(tmp_path)
        folder, output_dir = sie._discover_migrate_folder(tmp_path)
        assert folder == tmp_path / "issues"
        assert output_dir == tmp_path

    def test_case2_cwd_is_itself_issues_folder(self, tmp_path: Path):
        """CWD itself looks like an issues folder → migrate CWD, output to parent."""
        parent = tmp_path / "parent"
        parent.mkdir()
        cwd = parent / "issues"
        cwd.mkdir()
        cat = cwd / "Some_category"
        cat.mkdir()
        (cat / "L42.json").write_text("{}", encoding="utf-8")
        folder, output_dir = sie._discover_migrate_folder(cwd)
        assert folder == cwd
        assert output_dir == parent

    def test_refuses_at_git_root(self, tmp_path: Path):
        """Auto-discovery at a git root is too risky — refuse."""
        (tmp_path / ".git").mkdir()
        with pytest.raises(RuntimeError, match="git root"):
            sie._discover_migrate_folder(tmp_path)

    def test_refuses_when_output_already_exists_case1(self, tmp_path: Path):
        """If CWD/sonar-issues.md already exists (case 1), refuse to clobber."""
        self._build_issues_folder(tmp_path)
        (tmp_path / "sonar-issues.md").write_text("existing", encoding="utf-8")
        with pytest.raises(RuntimeError, match="already exists"):
            sie._discover_migrate_folder(tmp_path)

    def test_refuses_when_output_already_exists_case2(self, tmp_path: Path):
        """If parent/sonar-issues.md already exists (case 2), refuse to clobber."""
        parent = tmp_path / "parent"
        parent.mkdir()
        cwd = parent / "issues"
        cwd.mkdir()
        cat = cwd / "Some_category"
        cat.mkdir()
        (cat / "L42.json").write_text("{}", encoding="utf-8")
        (parent / "sonar-issues.md").write_text("existing", encoding="utf-8")
        with pytest.raises(RuntimeError, match="already exists"):
            sie._discover_migrate_folder(cwd)

    def test_errors_when_no_issues_folder_found(self, tmp_path: Path):
        """Neither issues/ subfolder nor cwd-as-issues → helpful error."""
        with pytest.raises(RuntimeError, match="Could not auto-discover"):
            sie._discover_migrate_folder(tmp_path)
