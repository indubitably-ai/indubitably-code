import json
from pathlib import Path

import pytest

from tools_run_terminal_cmd import run_terminal_cmd_impl


def test_run_terminal_cmd_echo():
    result = run_terminal_cmd_impl({"command": "echo hello", "is_background": False})
    assert result.success is True
    output = json.loads(result.content)

    assert output["metadata"]["exit_code"] == 0
    assert output["metadata"]["timed_out"] is False
    assert output["metadata"]["duration_seconds"] >= 0
    assert output["output"].startswith("hello")


def test_run_terminal_cmd_background_rejects_stdin():
    with pytest.raises(ValueError) as exc:
        run_terminal_cmd_impl({
            "command": "echo hi",
            "is_background": True,
            "stdin": "data",
        })
    assert "background" in str(exc.value)


def test_run_terminal_cmd_background_returns_formatted_output(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tools_run_terminal_cmd._LOG_DIR", tmp_path)

    result = run_terminal_cmd_impl({
        "command": "echo background",
        "is_background": True,
    })
    assert result.success is True
    output = json.loads(result.content)

    assert output["metadata"]["exit_code"] == 0
    assert output["metadata"]["timed_out"] is False
    content = output["output"]
    assert "background command dispatched" in content
    assert "job_id:" in content
    assert str(tmp_path) in content


def test_run_terminal_cmd_env_overrides(tmp_path: Path, monkeypatch):
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\necho $FOO", encoding="utf-8")
    script.chmod(0o755)

    cmd = f"{script}"
    result = run_terminal_cmd_impl({
        "command": cmd,
        "is_background": False,
        "env": {"FOO": "BAR"},
    })
    assert result.success is True
    output = json.loads(result.content)
    assert output["metadata"]["exit_code"] == 0
    assert output["output"].strip() == "BAR"
