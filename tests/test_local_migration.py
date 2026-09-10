"""Tests for sie.parse_local_export — 0.2.x folder → issues + rules.

Uses the `sample_local_export` fixture from conftest.py, which mirrors
the layout documented in sonarqube-workflow-SKILL.md and the actual
archive/0.1.2/issues/ shape.
"""

from __future__ import annotations

from pathlib import Path

import sie


class TestParseLocalExportBasics:
    def test_finds_all_l_json_files(self, sample_local_export: Path):
        issues, rules = sie.parse_local_export(sample_local_export)
        # 1 issue in cat1 (L128.json), 1 issue in cat2 (Lunknown.json)
        assert len(issues) == 2

    def test_groups_by_rule_field(self, sample_local_export: Path):
        """Issues are grouped by the `rule` field inside each JSON — more
        reliable than the trimmed folder name."""
        issues, rules = sie.parse_local_export(sample_local_export)
        rule_keys = set(rules.keys())
        assert rule_keys == {"python:S3776", "text:S8565"}

    def test_keeps_field_order_from_keep_fields(self, sample_local_export: Path):
        """The cleaned issue dicts must follow KEEP_FIELDS order so the
        rendered JSON is consistent with the 0.2.x export format."""
        issues, _ = sie.parse_local_export(sample_local_export)
        # Find the python:S3776 issue
        s3776 = next(i for i in issues if i["rule"] == "python:S3776")
        keys = list(s3776.keys())
        # KEEP_FIELDS = rule, component, line, textRange, message, severity, ...
        assert keys[0] == "rule"
        assert keys[1] == "component"
        assert keys[2] == "line"
        assert keys[3] == "textRange"
        assert keys[4] == "message"
        assert keys[5] == "severity"

    def test_loads_why_md_content(self, sample_local_export: Path):
        _, rules = sie.parse_local_export(sample_local_export)
        assert "Cognitive Complexity" in rules["python:S3776"]["why"]

    def test_loads_how_md_content_when_present(self, sample_local_export: Path):
        _, rules = sie.parse_local_export(sample_local_export)
        assert "Extract helpers" in rules["python:S3776"]["how"]

    def test_how_md_empty_when_absent(self, sample_local_export: Path):
        """Category folders without a how.md must produce an empty string,
        not raise — the renderer handles the missing-content case."""
        _, rules = sie.parse_local_export(sample_local_export)
        assert rules["text:S8565"]["how"] == ""


class TestParseLocalExportClosedIssueMarker:
    def test_lunknown_json_handled(self, sample_local_export: Path):
        """Lunknown.json is the closed-issue marker (line: null in the API).
        parse_local_export must handle it without crashing, and the issue's
        line field should be None (the closed-issue gotcha)."""
        issues, _ = sie.parse_local_export(sample_local_export)
        s8565 = next(i for i in issues if i["rule"] == "text:S8565")
        assert s8565["line"] is None

    def test_lunknown_filename_pattern_does_not_match_other_files(
        self, sample_local_export: Path, tmp_path: Path,
    ):
        """Files that don't match L<digits>.json or Lunknown.json must be
        ignored. Add a stray README.md to verify."""
        stray = sample_local_export / "Refactor_this_function_to_reduce_its_Cognitive_Complexity" / "README.md"
        stray.write_text("# This should be ignored\n", encoding="utf-8")
        issues, _ = sie.parse_local_export(sample_local_export)
        # Still 2 issues, README.md didn't get parsed as an issue
        assert len(issues) == 2


class TestParseLocalExportKeyHandling:
    def test_synthetic_key_for_missing_key_field(
        self, sample_local_export: Path,
    ):
        """Older 0.2.x exports may not include a `key` field. parse_local_export
        synthesizes one with a `local:` prefix so it's visually distinct from
        real API keys."""
        issues, _ = sie.parse_local_export(sample_local_export)
        for issue in issues:
            # The fixture's JSON files don't have a `key` field, so the
            # synthesized key should start with `local:`.
            assert issue["key"].startswith("local:")

    def test_real_key_field_preserved(self, sample_local_export: Path):
        """If the JSON has a real `key` field, it should be preserved."""
        # Add a key field to one of the issue JSONs
        import json
        s3776_path = (
            sample_local_export
            / "Refactor_this_function_to_reduce_its_Cognitive_Complexity"
            / "L128.json"
        )
        data = json.loads(s3776_path.read_text())
        data["key"] = "AaBprftR68fRE0gxBFjx"
        s3776_path.write_text(json.dumps(data))
        issues, _ = sie.parse_local_export(sample_local_export)
        s3776 = next(i for i in issues if i["rule"] == "python:S3776")
        # Real key preserved, no local: prefix
        assert s3776["key"] == "AaBprftR68fRE0gxBFjx"
        assert not s3776["key"].startswith("local:")


class TestParseLocalExportErrorHandling:
    def test_nonexistent_dir_raises(self, tmp_path: Path):
        with __import__("pytest").raises(NotADirectoryError):
            sie.parse_local_export(tmp_path / "does-not-exist")

    def test_empty_dir_returns_empty_lists(self, tmp_path: Path):
        """An empty dir produces no issues and no rules — not an error."""
        empty = tmp_path / "empty-issues"
        empty.mkdir()
        issues, rules = sie.parse_local_export(empty)
        assert issues == []
        assert rules == {}

    def test_malformed_json_skipped_with_warning(
        self, sample_local_export: Path, capsys,
    ):
        """Malformed JSON should be skipped (not crash), with a stderr warning."""
        bad = (
            sample_local_export
            / "Refactor_this_function_to_reduce_its_Cognitive_Complexity"
            / "L999.json"
        )
        bad.write_text("{not valid json", encoding="utf-8")
        issues, _ = sie.parse_local_export(sample_local_export)
        # The bad file was skipped — still 2 valid issues
        assert len(issues) == 2
        captured = capsys.readouterr()
        assert "malformed" in captured.err.lower()
