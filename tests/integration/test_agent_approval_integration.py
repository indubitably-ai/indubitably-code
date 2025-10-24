"""Integration tests for approval policy in agent.py."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent import Tool, run_agent
from session import SessionSettings, ContextSession
from tests.integration.helpers import queue_tool_turn
from tools_create_file import create_file_impl, create_file_tool_def


def _build_create_file_tool() -> Tool:
    definition = create_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=create_file_impl,
        capabilities={"write_fs"},
    )


def test_write_tool_prompts_for_approval_with_on_write_policy(
    integration_workspace,
    anthropic_mock,
    fake_figlet,
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    """Test that write tools prompt for user approval when policy is on_write."""

    # Set up approval policy via config file
    config_path = tmp_path / "config.toml"
    config_path.write_text('[execution]\napproval = "on_write"\n')
    monkeypatch.setenv("INDUBITABLY_SESSION_CONFIG", str(config_path))

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Queue a tool turn that requests file creation
    queue_tool_turn(
        client,
        tool_name="create_file",
        payloads=[{"path": "test.txt", "content": "approved content"}],
        final_text="Created test.txt after approval.",
        preamble_text="Requesting to create test.txt.",
    )

    # Mock input to simulate user approving
    approval_responses = ["y"]  # User says yes
    user_inputs = ["create test.txt", ""]  # Initial prompt, then EOF

    def mock_input(prompt: str = "") -> str:
        if "Allow this operation?" in prompt:
            if approval_responses:
                return approval_responses.pop(0)
            return "n"
        if user_inputs:
            return user_inputs.pop(0)
        raise EOFError

    monkeypatch.setattr("builtins.input", mock_input)

    # Mock InputHandler to use regular input for testing
    with patch("agent.InputHandler") as mock_handler_class:
        mock_handler = mock_handler_class.return_value
        mock_handler.get_input.side_effect = lambda prompt: mock_input(prompt)
        mock_handler.cleanup.return_value = None

        try:
            run_agent([_build_create_file_tool()], use_color=False)
        except EOFError:
            pass  # Expected when test input runs out

    captured = capsys.readouterr()

    # Verify approval prompt was shown
    assert "Approval Required" in captured.out
    assert "create_file" in captured.out
    assert "test.txt" in captured.out

    # Verify file was created (because user approved)
    created_file = integration_workspace.path("test.txt")
    assert created_file.exists()
    assert created_file.read_text() == "approved content"


def test_write_tool_denied_when_user_rejects(
    integration_workspace,
    anthropic_mock,
    fake_figlet,
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    """Test that write tools are denied when user rejects approval."""

    # Set up approval policy via config file
    config_path = tmp_path / "config.toml"
    config_path.write_text('[execution]\napproval = "on_write"\n')
    monkeypatch.setenv("INDUBITABLY_SESSION_CONFIG", str(config_path))

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Queue a tool turn that requests file creation
    queue_tool_turn(
        client,
        tool_name="create_file",
        payloads=[{"path": "denied.txt", "content": "should not exist"}],
        final_text="Attempted to create denied.txt.",
        preamble_text="Requesting to create denied.txt.",
    )

    # Mock input to simulate user denying
    approval_responses = ["n"]  # User says no
    user_inputs = ["create denied.txt", ""]  # Initial prompt, then EOF

    def mock_input(prompt: str = "") -> str:
        if "Allow this operation?" in prompt:
            if approval_responses:
                return approval_responses.pop(0)
            return "n"
        if user_inputs:
            return user_inputs.pop(0)
        raise EOFError

    monkeypatch.setattr("builtins.input", mock_input)

    # Mock InputHandler
    with patch("agent.InputHandler") as mock_handler_class:
        mock_handler = mock_handler_class.return_value
        mock_handler.get_input.side_effect = lambda prompt: mock_input(prompt)
        mock_handler.cleanup.return_value = None

        try:
            run_agent([_build_create_file_tool()], use_color=False)
        except EOFError:
            pass  # Expected when test input runs out

    captured = capsys.readouterr()

    # Verify approval prompt was shown
    assert "Approval Required" in captured.out

    # Verify denial message was shown
    assert "denied by user" in captured.out or "denied by approval" in captured.out.lower()

    # Verify file was NOT created (because user denied)
    denied_file = integration_workspace.path("denied.txt")
    assert not denied_file.exists()


def test_write_tool_no_prompt_when_policy_is_never(
    integration_workspace,
    anthropic_mock,
    fake_figlet,
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    """Test that write tools execute without prompting when policy is never."""

    # Set approval policy to never via config file
    config_path = tmp_path / "config.toml"
    config_path.write_text('[execution]\napproval = "never"\n')
    monkeypatch.setenv("INDUBITABLY_SESSION_CONFIG", str(config_path))

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Queue a tool turn that requests file creation
    queue_tool_turn(
        client,
        tool_name="create_file",
        payloads=[{"path": "auto.txt", "content": "no approval needed"}],
        final_text="Created auto.txt without approval.",
        preamble_text="Creating auto.txt.",
    )

    # Mock input - no approval responses needed
    user_inputs = ["create auto.txt", ""]  # Initial prompt, then EOF

    def mock_input(prompt: str = "") -> str:
        if user_inputs:
            return user_inputs.pop(0)
        raise EOFError

    monkeypatch.setattr("builtins.input", mock_input)

    # Mock InputHandler
    with patch("agent.InputHandler") as mock_handler_class:
        mock_handler = mock_handler_class.return_value
        mock_handler.get_input.side_effect = lambda prompt: mock_input(prompt)
        mock_handler.cleanup.return_value = None

        try:
            run_agent([_build_create_file_tool()], use_color=False)
        except EOFError:
            pass  # Expected when test input runs out

    captured = capsys.readouterr()

    # Verify NO approval prompt was shown
    assert "Approval Required" not in captured.out

    # Verify file WAS created (no approval needed)
    auto_file = integration_workspace.path("auto.txt")
    assert auto_file.exists()
    assert auto_file.read_text() == "no approval needed"
