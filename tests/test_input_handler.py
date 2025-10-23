"""Tests for input_handler module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from prompt_toolkit.history import FileHistory

from input_handler import (
    DEFAULT_HISTORY_DIR,
    DEFAULT_HISTORY_FILE,
    MAX_HISTORY_ENTRIES,
    HistoryManager,
    InputHandler,
)


class TestHistoryManager:
    """Test HistoryManager class."""

    def test_init_with_defaults(self) -> None:
        """Test HistoryManager initialization with defaults."""
        manager = HistoryManager()
        assert manager.history_file == DEFAULT_HISTORY_FILE
        assert manager.max_entries == MAX_HISTORY_ENTRIES

    def test_init_with_custom_values(self, tmp_path: Path) -> None:
        """Test HistoryManager initialization with custom values."""
        custom_file = tmp_path / "custom_history.txt"
        manager = HistoryManager(history_file=custom_file, max_entries=50)
        assert manager.history_file == custom_file
        assert manager.max_entries == 50

    def test_ensure_history_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test that history directory is created."""
        history_file = tmp_path / "subdir" / "history.txt"
        manager = HistoryManager(history_file=history_file)
        assert history_file.parent.exists()

    def test_ensure_history_dir_handles_permission_error(self) -> None:
        """Test that permission errors are handled gracefully."""
        # Use a path that will likely fail on permission
        with patch("pathlib.Path.mkdir", side_effect=PermissionError):
            manager = HistoryManager(history_file=Path("/root/history.txt"))
            # Should not raise an exception
            assert manager.history_file == Path("/root/history.txt")

    def test_rotate_history_with_no_file(self, tmp_path: Path) -> None:
        """Test rotate_history when file doesn't exist."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file)
        # Should not raise an exception
        manager.rotate_history()

    def test_rotate_history_keeps_max_entries(self, tmp_path: Path) -> None:
        """Test that rotate_history keeps only max_entries."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file, max_entries=5)

        # Create a history file with 10 entries
        with open(history_file, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(f"command {i}\n")

        manager.rotate_history()

        # Check that only the last 5 entries remain
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 5
        assert lines[0] == "command 5\n"
        assert lines[4] == "command 9\n"

    def test_rotate_history_does_nothing_when_under_limit(self, tmp_path: Path) -> None:
        """Test that rotate_history doesn't modify file when under limit."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file, max_entries=10)

        # Create a history file with 5 entries
        with open(history_file, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"command {i}\n")

        manager.rotate_history()

        # Check that all entries remain
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_rotate_history_handles_permission_error(self, tmp_path: Path) -> None:
        """Test that rotate_history handles permission errors gracefully."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file)

        # Create file
        with open(history_file, "w", encoding="utf-8") as f:
            f.write("command\n")

        # Mock open to raise permission error
        with patch("builtins.open", side_effect=PermissionError):
            # Should not raise an exception
            manager.rotate_history()

    def test_rotate_history_handles_unicode_error(self, tmp_path: Path) -> None:
        """Test that rotate_history handles unicode decode errors gracefully."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file)

        # Create file with invalid UTF-8
        with open(history_file, "wb") as f:
            f.write(b"\xff\xfe invalid utf-8")

        # Should not raise an exception
        manager.rotate_history()

    def test_get_file_history_returns_file_history(self, tmp_path: Path) -> None:
        """Test that get_file_history returns FileHistory object."""
        history_file = tmp_path / "history.txt"
        manager = HistoryManager(history_file=history_file)

        file_history = manager.get_file_history()
        assert isinstance(file_history, FileHistory)

    def test_get_file_history_handles_permission_error(self) -> None:
        """Test that get_file_history handles permission errors gracefully."""
        with patch("input_handler.FileHistory", side_effect=PermissionError):
            manager = HistoryManager()
            file_history = manager.get_file_history()
            assert file_history is None


class TestInputHandler:
    """Test InputHandler class."""

    def test_init_with_defaults(self) -> None:
        """Test InputHandler initialization with defaults."""
        handler = InputHandler()
        assert handler.history_manager is not None
        assert handler._session is None

    def test_init_with_custom_history_manager(self, tmp_path: Path) -> None:
        """Test InputHandler initialization with custom history manager."""
        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)
        assert handler.history_manager is manager

    def test_get_session_creates_session(self, tmp_path: Path) -> None:
        """Test that _get_session creates a PromptSession."""
        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)

        session = handler._get_session()
        assert session is not None
        assert handler._session is session

    def test_get_session_reuses_session(self, tmp_path: Path) -> None:
        """Test that _get_session reuses the same session."""
        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)

        session1 = handler._get_session()
        session2 = handler._get_session()
        assert session1 is session2

    @patch("input_handler.PromptSession")
    def test_get_input_returns_user_input(self, mock_session_class: Mock, tmp_path: Path) -> None:
        """Test that get_input returns user input."""
        mock_session = MagicMock()
        mock_session.prompt.return_value = "test input"
        mock_session_class.return_value = mock_session

        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)

        result = handler.get_input(">>> ")
        assert result == "test input"
        mock_session.prompt.assert_called_once_with(">>> ")

    @patch("input_handler.PromptSession")
    def test_get_input_rotates_history_on_success(self, mock_session_class: Mock, tmp_path: Path) -> None:
        """Test that get_input rotates history after successful input."""
        mock_session = MagicMock()
        mock_session.prompt.return_value = "test input"
        mock_session_class.return_value = mock_session

        history_file = tmp_path / "history.txt"
        # Create file with entries
        with open(history_file, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(f"command {i}\n")

        manager = HistoryManager(history_file=history_file, max_entries=5)
        handler = InputHandler(history_manager=manager)

        handler.get_input(">>> ")

        # Check that history was rotated
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 5

    @patch("input_handler.PromptSession")
    def test_get_input_propagates_eof_error(self, mock_session_class: Mock, tmp_path: Path) -> None:
        """Test that get_input propagates EOFError."""
        mock_session = MagicMock()
        mock_session.prompt.side_effect = EOFError
        mock_session_class.return_value = mock_session

        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)

        with pytest.raises(EOFError):
            handler.get_input(">>> ")

    @patch("input_handler.PromptSession")
    def test_get_input_propagates_keyboard_interrupt(self, mock_session_class: Mock, tmp_path: Path) -> None:
        """Test that get_input propagates KeyboardInterrupt."""
        mock_session = MagicMock()
        mock_session.prompt.side_effect = KeyboardInterrupt
        mock_session_class.return_value = mock_session

        manager = HistoryManager(history_file=tmp_path / "history.txt")
        handler = InputHandler(history_manager=manager)

        with pytest.raises(KeyboardInterrupt):
            handler.get_input(">>> ")

    @patch("input_handler.PromptSession")
    def test_get_input_rotates_on_eof(self, mock_session_class: Mock, tmp_path: Path) -> None:
        """Test that get_input rotates history even on EOF."""
        mock_session = MagicMock()
        mock_session.prompt.side_effect = EOFError
        mock_session_class.return_value = mock_session

        history_file = tmp_path / "history.txt"
        # Create file with entries
        with open(history_file, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(f"command {i}\n")

        manager = HistoryManager(history_file=history_file, max_entries=5)
        handler = InputHandler(history_manager=manager)

        with pytest.raises(EOFError):
            handler.get_input(">>> ")

        # Check that history was rotated despite the error
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_cleanup_rotates_history(self, tmp_path: Path) -> None:
        """Test that cleanup rotates history."""
        history_file = tmp_path / "history.txt"
        # Create file with entries
        with open(history_file, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(f"command {i}\n")

        manager = HistoryManager(history_file=history_file, max_entries=5)
        handler = InputHandler(history_manager=manager)

        handler.cleanup()

        # Check that history was rotated
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 5
