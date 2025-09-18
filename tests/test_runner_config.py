import textwrap

import pytest

from runner_config import RunnerConfig, load_runner_config


def test_load_runner_config_parses_values(tmp_path):
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [runner]
            max_turns = 6
            exit_on_tool_error = true
            dry_run = false
            allowed_tools = ["read_file", "list_files"]
            blocked_tools = "edit_file"
            audit_log = "logs/audit.jsonl"
            changes_log = "changes.jsonl"
            """
        ),
        encoding="utf-8",
    )

    cfg = load_runner_config(config_path)

    assert cfg.max_turns == 6
    assert cfg.exit_on_tool_error is True
    assert cfg.dry_run is False
    assert cfg.allowed_tools == {"read_file", "list_files"}
    assert cfg.blocked_tools == {"edit_file"}
    assert cfg.audit_log_path == (config_path.parent / "logs/audit.jsonl").resolve()
    assert cfg.changes_log_path == (config_path.parent / "changes.jsonl").resolve()


def test_load_runner_config_defaults_when_missing(tmp_path):
    config_path = tmp_path / "empty.toml"
    config_path.write_text("", encoding="utf-8")

    cfg = load_runner_config(config_path)

    assert cfg == RunnerConfig()


def test_load_runner_config_errors(tmp_path):
    config_path = tmp_path / "bad.toml"
    config_path.write_text("[runner]\nallowed_tools = 42\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_runner_config(config_path)
