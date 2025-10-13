import pytest

from tools.schemas import ReadFileInput, RunTerminalCmdInput, validate_tool_input


def test_read_file_input_defaults():
    model = ReadFileInput(path="README.md")
    data = model.dump()
    assert data["path"] == "README.md"
    assert data["encoding"] == "utf-8"
    assert data["errors"] == "replace"


def test_run_terminal_cmd_rejects_dangerous_command():
    with pytest.raises(ValueError) as exc:
        RunTerminalCmdInput(command="rm -rf /")
    assert "dangerous" in str(exc.value)


def test_validate_tool_input_uses_schema():
    data = validate_tool_input("read_file", {"path": "file.txt", "tail_lines": 10})
    assert data == {"path": "file.txt", "encoding": "utf-8", "errors": "replace", "tail_lines": 10}


def test_validate_tool_input_unknown_tool_pass_through():
    payload = {"custom": True}
    assert validate_tool_input("unknown", payload) == payload
