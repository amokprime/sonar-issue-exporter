"""Shared pytest fixtures and config for the sonar-issue-exporter test suite.

Adds the repo root to sys.path so test files can `import sie` without
needing sie.py to be installed as a package. Run tests from the repo
root: `pytest tests/`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make sie.py importable as a module. The tests live in tests/, sie.py
# lives one level up. Inserting at position 0 means it takes priority
# over any installed `sie` package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sie  # noqa: E402  — path manipulation must come first


@pytest.fixture
def sample_local_export(tmp_path: Path) -> Path:
    """Build a minimal 0.2.x local-export folder under tmp_path.

    Mirrors the layout documented in sonarqube-workflow-SKILL.md and
    archive/0.1.2/issues/:

        <root>/
          Refactor_this_function_to_reduce_its_Cognitive_Complexity/
            L128.json
            why.md
            how.md
          Dependency_versions_are_not_predictable_if_the_lock_file/
            Lunknown.json     # closed-issue marker (line: null in API)
            why.md
            # how.md intentionally absent — some rules have no fix guidance
    """
    root = tmp_path / "issues"

    cat1 = root / "Refactor_this_function_to_reduce_its_Cognitive_Complexity"
    cat1.mkdir(parents=True)
    (cat1 / "L128.json").write_text(json.dumps({
        "rule": "python:S3776",
        "component": "amokprime_sonar-issue-exporter:sie.py",
        "line": 128,
        "textRange": {
            "startLine": 128, "endLine": 128,
            "startOffset": 4, "endOffset": 8,
        },
        "message": "Refactor this function to reduce its Cognitive Complexity.",
        "severity": "CRITICAL",
        "type": "CODE_SMELL",
        "cleanCodeAttribute": "FOCUSED",
        "cleanCodeAttributeCategory": "ADAPTABLE",
        "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "HIGH"}],
        "flows": [],
    }), encoding="utf-8")
    (cat1 / "why.md").write_text(
        "# Why is this an issue?\n\n"
        "Cognitive Complexity is a measure of how hard it is to read "
        "and understand a function.\n",
        encoding="utf-8",
    )
    (cat1 / "how.md").write_text(
        "# How can I fix it?\n\n"
        "- Extract helpers\n- Use early returns\n",
        encoding="utf-8",
    )

    cat2 = root / "Dependency_versions_are_not_predictable_if_the_lock_file"
    cat2.mkdir(parents=True)
    (cat2 / "Lunknown.json").write_text(json.dumps({
        "rule": "text:S8565",
        "component": "amokprime_sonar-issue-exporter:pyproject.toml",
        "message": "Dependency versions are not predictable if the lock file is missing.",
        "severity": "MAJOR",
        "type": "VULNERABILITY",
        "cleanCodeAttribute": "COMPLETE",
        "cleanCodeAttributeCategory": "INTENTIONAL",
        "impacts": [{"softwareQuality": "SECURITY", "severity": "MEDIUM"}],
        "flows": [],
    }), encoding="utf-8")
    (cat2 / "why.md").write_text(
        "Lock files pin exact dependency versions.\n",
        encoding="utf-8",
    )
    # how.md intentionally absent — exercises the "no how.md content" branch.

    return root


@pytest.fixture
def fake_repo_with_package_json(tmp_path: Path) -> Path:
    """Build a fake repo with a package.json pointing at amokprime/linebyline.

    Used for testing the CWD-aware single-token shortcuts (`sie main`,
    `sie pr`, `sie staging`, bare `sie`).
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "linebyline",
        "version": "1.0.0",
        "repository": {
            "type": "git",
            "url": "https://github.com/amokprime/linebyline.git",
        },
    }), encoding="utf-8")
    return tmp_path


@pytest.fixture
def fake_repo_with_pyproject_toml(tmp_path: Path) -> Path:
    """Build a fake repo with a pyproject.toml (no [project.urls])
    and a git remote pointing at amokprime/sonar-issue-exporter.

    Used for testing the git-remote fallback in discover_repo().
    """
    import subprocess
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools>=64"]\n'
        '[project]\nname="sonar-issue-exporter"\nversion="1.0.0"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-q"], cwd=tmp_path, check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin",
         "https://github.com/amokprime/sonar-issue-exporter.git"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path