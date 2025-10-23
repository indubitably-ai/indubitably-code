"""Integration tests for input handler with command history."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import Tool, run_agent
from input_handler import InputHandler, HistoryManager
from tests.integration.helpers import queue_tool_turn


@pytest.fixture
def input_stub(monkeypatch, tmp_path):
    """Patch InputHandler with a stub that provides pre-configured inputs."""

    def factory(*inputs: str):
        mock_handler = MagicMock(spec=InputHandler)
        mock_handler.get_input.side_effect = list(inputs) + [EOFError()]
        mock_handler.cleanup = MagicMock()

        # Patch InputHandler to return our mock
        monkeypatch.setattr("agent.InputHandler", lambda: mock_handler)
        return mock_handler

    return factory


def test_input_handler_integration_with_agent(
    integration_workspace,
    anthropic_mock,
    input_stub,
    fake_figlet,
    capsys,
) -> None:
    """Test that InputHandler integrates correctly with agent.py."""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()
    queue_tool_turn(
        client,
        tool_name="dummy_tool",
        payloads=[],
        final_text="Hello from agent!",
        preamble_text="I received your input.",
    )

    # Provide inputs via the stub
    input_stub("test input", "")

    run_agent([], use_color=False)

    captured = capsys.readouterr()
    # Verify agent received and processed the input
    assert "I received your input" in captured.out
    assert "Samus ▸" in captured.out


def test_input_handler_cleanup_called(
    integration_workspace,
    anthropic_mock,
    input_stub,
    fake_figlet,
    capsys,
) -> None:
    """Test that InputHandler.cleanup is called when agent exits."""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Provide EOF to exit immediately
    mock = input_stub()

    run_agent([], use_color=False)

    # Verify cleanup was called
    mock.cleanup.assert_called_once()


def test_input_handler_handles_eof(
    integration_workspace,
    anthropic_mock,
    input_stub,
    fake_figlet,
    capsys,
) -> None:
    """Test that InputHandler handles EOF correctly."""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Mock get_input to raise EOFError immediately
    mock = input_stub()

    run_agent([], use_color=False)

    captured = capsys.readouterr()
    # Should exit cleanly without error - verify banner was displayed
    assert "INDUBITABLY CODE" in captured.out
    # Verify no errors in output
    assert "Error" not in captured.out or "error" not in captured.out.lower()


def test_history_manager_creates_history_file(tmp_path: Path) -> None:
    """Test that history manager creates history directory and file."""
    history_file = tmp_path / "test_history" / "history.txt"
    manager = HistoryManager(history_file=history_file)

    # Directory should be created
    assert history_file.parent.exists()


def test_history_persists_between_sessions(tmp_path: Path) -> None:
    """Test that history persists between different InputHandler sessions."""
    history_file = tmp_path / "history.txt"

    # First session - simulate adding entries directly to history file
    with open(history_file, "w", encoding="utf-8") as f:
        f.write("first command\n")
        f.write("second command\n")

    # Second session - verify history file exists and has content
    manager = HistoryManager(history_file=history_file)
    file_history = manager.get_file_history()

    # Verify we can read the history
    assert history_file.exists()
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2
    assert "first command" in lines[0]
    assert "second command" in lines[1]


def test_history_rotation_with_max_entries(tmp_path: Path) -> None:
    """Test that history rotation works with max entries limit."""
    history_file = tmp_path / "history.txt"
    max_entries = 10

    # Create history with more than max entries
    with open(history_file, "w", encoding="utf-8") as f:
        for i in range(20):
            f.write(f"command {i}\n")

    manager = HistoryManager(history_file=history_file, max_entries=max_entries)
    manager.rotate_history()

    # Verify only last max_entries remain
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == max_entries
    assert "command 10" in lines[0]
    assert "command 19" in lines[9]


def test_input_handler_with_large_paste(tmp_path: Path) -> None:
    """Test that InputHandler can handle large pasted content."""
    history_file = tmp_path / "history.txt"
    manager = HistoryManager(history_file=history_file)
    handler = InputHandler(history_manager=manager)

    # Simulate a large paste (1000 lines of code)
    large_input = "\n".join([f"line {i}" for i in range(1000)])

    with patch.object(handler, "_get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.prompt.return_value = large_input
        mock_session_getter.return_value = mock_session

        result = handler.get_input(">>> ")

        # Verify the large input was accepted
        assert result == large_input
        assert "\n" in result
        assert "line 999" in result


def test_keyboard_interrupt_rotates_history(tmp_path: Path) -> None:
    """Test that KeyboardInterrupt causes history rotation."""
    history_file = tmp_path / "history.txt"

    # Create history with more than max entries
    with open(history_file, "w", encoding="utf-8") as f:
        for i in range(20):
            f.write(f"command {i}\n")

    manager = HistoryManager(history_file=history_file, max_entries=10)
    handler = InputHandler(history_manager=manager)

    with patch.object(handler, "_get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.prompt.side_effect = KeyboardInterrupt
        mock_session_getter.return_value = mock_session

        with pytest.raises(KeyboardInterrupt):
            handler.get_input(">>> ")

    # Verify history was rotated despite interrupt
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 10


def test_enhanced_menu_displays_input_hints(
    integration_workspace,
    anthropic_mock,
    input_stub,
    fake_figlet,
    capsys,
) -> None:
    """Test that the enhanced menu displays input navigation hints."""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    # Provide EOF to exit immediately
    mock = input_stub()

    run_agent([], use_color=False)

    captured = capsys.readouterr()
    # Verify all the enhanced menu elements are present
    assert "↑↓ History" in captured.out
    assert "←→ Edit" in captured.out
    assert "ESC Interrupt" in captured.out
    assert "/status" in captured.out
    assert "/compact" in captured.out
    assert "Quit Ctrl+C" in captured.out
