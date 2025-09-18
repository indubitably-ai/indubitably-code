import json

from tools_run_terminal_cmd import run_terminal_cmd_impl


def test_run_terminal_cmd_echo():
    output = json.loads(run_terminal_cmd_impl({"command": "echo hello", "is_background": False}))

    assert output["ok"] is True
    assert output["returncode"] == 0
    assert output["stdout"].strip() == "hello"
    assert output["stderr"] == ""
