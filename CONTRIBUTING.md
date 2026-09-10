# Contributing to sonar-issue-exporter

This repo was vibe-coded with web chat AI agents ([DeepSeek](https://chat.deepseek.com/) and [Z.ai](https://chat.z.ai/)). The agent-facing workflow lives in `ai/chat.z.ai/`. If you're a human contributor (rare for this project, but welcome), the sections below cover the dev setup and the web chat deploy pipeline.

## Development setup

The `tests/` directory contains a pytest suite (~118 specs) covering URL parsing, GitHub URL mapping, fuzzy input resolution, local-folder migration, CLI disambiguation, output path resolution, Markdown rendering, and clean-mode suppression. Pure unit tests — no network calls, so they run in <1s.

```sh
# Clone the repo
git clone https://github.com/amokprime/sonar-issue-exporter.git
cd sonar-issue-exporter

# Install dev deps (creates .venv/):
uv sync --extra dev

# Run tests (pytest is in .venv/, not system-wide — use uv run):
uv run pytest tests/ -v                     # run all tests
uv run pytest tests/test_url_parsing.py -v   # single file
uv run pytest tests/ -k "clean" -v          # by keyword
```

**Why `uv sync` is the right approach**: `uv sync` is idempotent — if `.venv/` exists and `pyproject.toml` hasn't changed, it's a no-op. If deps changed (e.g. a new test file imports a new helper) or `.venv/` was deleted, it recreates the venv with the exact deps from `pyproject.toml`'s `[project.optional-dependencies] dev = [...]`. This is preferable to `pip install -e ".[dev]"` because `uv` resolves and locks deps faster, and `uv run` ensures the right Python interpreter is used without manual activation.

Lint with ruff (also in `.venv/`):

```sh
uv run ruff check --fix sie.py      # autofix safe violations
uv run ruff check sie.py            # gate — fails on any remaining violation
```

The rule set is `E,W,F,I,C90,UP,B` — pycodestyle, pyflakes, isort, mccabe complexity (C901, threshold 10), pyupgrade, flake8-bugbear. C901 (mccabe) and SonarCloud's S3776 (cognitive, threshold 15) measure different things — both are intentionally enabled; a function that exceeds EITHER metric warrants a refactor.

See [tests/README.md](https://github.com/amokprime/sonar-issue-exporter/tree/main/tests/README.md) for the file-by-file coverage map and design notes. 

See [ai/chat.z.ai/scripts/README.md](https://github.com/amokprime/sonar-issue-exporter/tree/main/ai/chat.z.ai/scripts/README.md) for a web chat deployment pipeline featuring chat.z.ai.

See [ai/chat.z.ai/AGENTS.md](https://github.com/amokprime/sonar-issue-exporter/tree/main/ai/chat.z.ai/AGENTS.md) for the agent-facing dev workflow.