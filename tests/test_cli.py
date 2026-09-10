"""Tests for sie.main — CLI positional disambiguation.

This is the regression test for the v1.0.0 disambiguation refactor.
Before the refactor, `sie <path>` was misinterpreted as a migration
input. After the refactor:

- `sie` (bare) → main of CWD → default output
- `sie <path>` → main of CWD → <path> (output-path-only)
- `sie <input> <path>` → input → <path>
- `sie --migrate <path>` → migration → <input_parent>/sonar-issues.md
- `sie --migrate <path> <output>` → migration → <output>
- `sie <path> <path>` (no --migrate) → ambiguous error
- `sie --migrate` (no path) → "requires a path argument"
- `sie --summary --migrate` → "not a valid combination"

These tests call main() directly with argv lists, then assert on the
exit code and the captured stderr. They mock export_url and export_local
so no network calls happen.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import sie


class TestBareSie:
    @patch("sie.export_url")
    @patch("sie.discover_repo")
    def test_bare_sie_resolves_to_main_of_cwd_repo(
        self, mock_discover, mock_export, tmp_path: Path,
    ):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main([])
        assert rc == 0
        mock_export.assert_called_once()
        # Inspect the descriptor that was passed to export_url
        call_kwargs = mock_export.call_args.kwargs
        assert call_kwargs["output_path"] is None
        assert call_kwargs["summary_mode"] is False
        descriptor = mock_export.call_args.args[0]
        assert descriptor["project"] == "amokprime_linebyline"
        assert descriptor["scope"] == "main"


class TestOutputPathOnly:
    """`sie <path>` (single path-like positional) → main of CWD → <path>."""

    @patch("sie.export_url")
    @patch("sie.discover_repo")
    def test_absolute_path_treated_as_output(
        self, mock_discover, mock_export, tmp_path: Path,
    ):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["/tmp/my-report.md"])
        assert rc == 0
        # export_url called with output_path=/tmp/my-report.md
        call_kwargs = mock_export.call_args.kwargs
        assert call_kwargs["output_path"] == "/tmp/my-report.md"

    @patch("sie.export_url")
    @patch("sie.discover_repo")
    def test_home_relative_path_treated_as_output(
        self, mock_discover, mock_export, tmp_path: Path,
    ):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["~/my-report.md"])
        assert rc == 0
        assert mock_export.call_args.kwargs["output_path"] == "~/my-report.md"

    @patch("sie.export_url")
    @patch("sie.discover_repo")
    def test_dot_slash_path_treated_as_output(
        self, mock_discover, mock_export, tmp_path: Path,
    ):
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["./local-output.md"])
        assert rc == 0
        assert mock_export.call_args.kwargs["output_path"] == "./local-output.md"


class TestInputAndOutput:
    """`sie <input> <output>` — explicit input (URL/fuzzy) + custom output."""

    @patch("sie.export_url")
    def test_url_input_with_output(self, mock_export, tmp_path: Path):
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main([
                "https://github.com/amokprime/linebyline/pull/11",
                "/tmp/out.md",
            ])
        assert rc == 0
        call_args = mock_export.call_args
        descriptor = call_args.args[0]
        assert descriptor["scope"] == "pr:11"
        assert call_args.kwargs["output_path"] == "/tmp/out.md"

    @patch("sie.export_url")
    def test_fuzzy_input_with_output(self, mock_export, tmp_path: Path):
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["amokprime/linebyline", "/tmp/out.md"])
        assert rc == 0
        descriptor = mock_export.call_args.args[0]
        assert descriptor["project"] == "amokprime_linebyline"
        assert descriptor["scope"] == "main"


class TestMigrateFlag:
    """`sie -m [path] [output]` — local-folder migration.

    The -m / --migrate flag now supports auto-discovery: `sie -m` with no
    path arg looks for an ``issues/`` subfolder in CWD, or checks if CWD
    itself is an issues folder. See ``sie._discover_migrate_folder``.
    """

    @patch("sie.export_local")
    def test_migrate_longform_with_path(self, mock_export, tmp_path: Path):
        mock_export.return_value = 0
        rc = sie.main(["--migrate", str(tmp_path)])
        assert rc == 0
        call_args = mock_export.call_args
        assert call_args.args[0] == tmp_path
        assert call_args.kwargs["output_path"] is None

    @patch("sie.export_local")
    def test_migrate_shortform_with_path(self, mock_export, tmp_path: Path):
        """-m is the shortform for --migrate."""
        mock_export.return_value = 0
        rc = sie.main(["-m", str(tmp_path)])
        assert rc == 0
        call_args = mock_export.call_args
        assert call_args.args[0] == tmp_path

    @patch("sie.export_local")
    def test_migrate_with_path_and_output(self, mock_export, tmp_path: Path):
        mock_export.return_value = 0
        rc = sie.main(["-m", str(tmp_path), "/tmp/out.md"])
        assert rc == 0
        call_args = mock_export.call_args
        assert call_args.args[0] == tmp_path
        assert call_args.kwargs["output_path"] == "/tmp/out.md"

    @patch("sie.export_local")
    def test_migrate_auto_discover_passes_none(
        self, mock_export, tmp_path: Path,
    ):
        """`sie -m` with no path arg passes ``folder=None`` to
        ``export_local``, which triggers ``_discover_migrate_folder``."""
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["-m"])
        assert rc == 0
        call_args = mock_export.call_args
        # folder is None (auto-discovery), cwd is passed through
        assert call_args.args[0] is None
        assert call_args.kwargs["cwd"] == tmp_path

    def test_migrate_with_summary_errors(self, tmp_path: Path):
        """--summary + --migrate is not a valid combination."""
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["--summary", "--migrate", str(tmp_path)])
        assert rc == 1


class TestAmbiguousPositionals:
    """`sie <path> <path>` without --migrate is ambiguous — must error."""

    def test_two_paths_without_migrate_errors(self, tmp_path: Path):
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["/tmp/foo", "/tmp/bar"])
        assert rc == 1

    def test_two_paths_error_message_mentions_migrate(self, tmp_path: Path, capsys):
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["/tmp/foo", "/tmp/bar"])
        captured = capsys.readouterr()
        assert "ambiguous" in captured.err.lower()
        # Error message should mention -m (the shortform) for --migrate
        assert "-m" in captured.err or "--migrate" in captured.err


class TestSummaryMode:
    @patch("sie.export_url")
    def test_summary_flag_passes_through(self, mock_export, tmp_path: Path):
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["--summary", "amokprime/linebyline"])
        assert rc == 0
        assert mock_export.call_args.kwargs["summary_mode"] is True

    @patch("sie.export_url")
    @patch("sie.discover_repo")
    def test_summary_with_output_path(
        self, mock_discover, mock_export, tmp_path: Path,
    ):
        """--summary + output-path-only: summary doesn't write a file, but the
        disambiguation should still treat the path as output (not migration)."""
        mock_discover.return_value = {
            "owner": "amokprime", "repo": "linebyline",
            "project": "amokprime_linebyline",
        }
        mock_export.return_value = 0
        with patch("sie.Path.cwd", return_value=tmp_path):
            rc = sie.main(["--summary", "/tmp/out.md"])
        assert rc == 0
        call_kwargs = mock_export.call_args.kwargs
        assert call_kwargs["summary_mode"] is True
        assert call_kwargs["output_path"] == "/tmp/out.md"