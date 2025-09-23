# Indubitably Code Agents.md Guide

This Agents.md file provides the operating guidelines for AI agents collaborating on the Indubitably Code repository.

## Project Structure Overview

- `/agent.py` – interactive Anthropic agent loop with tool execution and TUI helpers.
- `/agent_runner.py` – headless runner that powers the `indubitably-agent` CLI.
- `/cli.py` & `/run.py` – entry points for batch and interactive modes.
- `/prompt/` – prompt packing utilities and deterministic renderers.
- `/session/` – context history, compaction, pins, telemetry, and token metering.
- `/tools_*.py` – tool implementations (filesystem, search, MCP integrations, etc.).
- `/tests/` – pytest suite covering session behaviour, tools, and runners.
- `/examples/` – sample runner configuration files.

Keep new modules colocated with similar functionality and update imports accordingly.

## Coding Conventions for This Repository

### General Python Guidelines

- Target Python **3.13+** and prefer explicit type hints for new functions and classes.
- Default to **ASCII** for new or edited files unless the file already relies on Unicode.
- Match the existing minimal comment style; add concise comments only when logic is non-obvious.
- Honour the current logging/print patterns used by the agent for consistency.
- Never revert user-authored changes unless the user explicitly asks for it.

### Tooling and Shell Usage

- Prefer ripgrep (`rg`, `rg --files`) for code searches; only fall back when unavailable.
- When running shell commands, invoke `bash -lc` (not `cd`) and always provide `workdir`.
- Use `uv` for dependency management and execution (`uv sync`, `uv run ...`).
- Avoid network access or elevated permissions unless clearly required and approved.

### Session and Prompt Management

- Use `ContextSession` / `PromptPacker` for assembling prompts; do not bypass them.
- Respect compaction and pin budgets; persist important context with pins when necessary.
- Keep system instructions and guidance deterministic to aid reproducibility.

## Testing Requirements

Run the test suite after code changes that affect behaviour:

```bash
uv run pytest
```

Use `-k` for targeted runs when iterating on specific modules.

## Programmatic Checks

Before handing off changes, verify core checks succeed:

```bash
uv run pytest
uv run python -m compileall agent.py agent_runner.py session prompt
```

Add or update tests when you touch logic paths that lack coverage.

## Pull Request & Change Notes

1. Summarise what changed, why it was needed, and which modules were touched.
2. Highlight new files, configs, or tool capabilities that affect workflows.
3. State the validation performed (`uv run pytest`, manual verification, etc.).
4. Call out follow-up work, risks, or assumptions for the reviewer.

Keep PRs focused and incremental so tooling and reviewers can reason about them easily.
