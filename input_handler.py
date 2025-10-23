"""Input handler with command history support using prompt_toolkit."""

import os
import re
import sys
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import Input


DEFAULT_HISTORY_DIR = Path.home() / ".indubitably-code"
DEFAULT_HISTORY_FILE = DEFAULT_HISTORY_DIR / "history.txt"
MAX_HISTORY_ENTRIES = 100

# ANSI escape code pattern
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m')


def _format_prompt_for_toolkit(prompt: str) -> ANSI:
    """
    Format prompt string for prompt_toolkit.

    If the prompt contains ANSI escape codes, wrap it in ANSI() so
    prompt_toolkit interprets them correctly. Otherwise, return as-is.

    Args:
        prompt: Prompt string, possibly containing ANSI codes

    Returns:
        ANSI-wrapped prompt for proper rendering
    """
    # If prompt contains ANSI codes, wrap it so prompt_toolkit handles them
    if ANSI_ESCAPE_PATTERN.search(prompt):
        return ANSI(prompt)
    return prompt


class HistoryManager:
    """Manages command history with rotation to limit entries."""

    def __init__(self, history_file: Optional[Path] = None, max_entries: int = MAX_HISTORY_ENTRIES):
        """
        Initialize history manager.

        Args:
            history_file: Path to history file. Defaults to ~/.indubitably-code/history.txt
            max_entries: Maximum number of history entries to keep
        """
        self.history_file = history_file or DEFAULT_HISTORY_FILE
        self.max_entries = max_entries
        self._ensure_history_dir()

    def _ensure_history_dir(self) -> None:
        """Create history directory if it doesn't exist."""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            # If we can't create the directory, we'll operate without persistent history
            pass

    def rotate_history(self) -> None:
        """Rotate history file to keep only the last max_entries."""
        if not self.history_file.exists():
            return

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Keep only the last max_entries
            if len(lines) > self.max_entries:
                lines = lines[-self.max_entries:]
                with open(self.history_file, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        except (OSError, PermissionError, UnicodeDecodeError):
            # If rotation fails, continue without it
            pass

    def get_file_history(self) -> Optional[FileHistory]:
        """
        Get FileHistory object for prompt_toolkit.

        Returns:
            FileHistory object or None if history file is not accessible
        """
        try:
            return FileHistory(str(self.history_file))
        except (OSError, PermissionError):
            return None


class InputHandler:
    """Handles user input with history, editing, and paste support."""

    def __init__(self, history_manager: Optional[HistoryManager] = None, custom_input: Optional[Input] = None):
        """
        Initialize input handler.

        Args:
            history_manager: HistoryManager instance. Creates default if None.
            custom_input: Custom input for prompt_toolkit. Used for testing.
        """
        self.history_manager = history_manager or HistoryManager()
        self._session: Optional[PromptSession] = None
        self._custom_input = custom_input
        self._fallback_mode = False

    def _get_session(self) -> Optional[PromptSession]:
        """Get or create PromptSession, or None if in fallback mode."""
        if self._fallback_mode:
            return None

        if self._session is None:
            try:
                file_history = self.history_manager.get_file_history()
                kwargs = {
                    "history": file_history,
                    "enable_history_search": True,
                    "multiline": False,  # Single line by default, but handles pastes
                }
                if self._custom_input is not None:
                    kwargs["input"] = self._custom_input
                self._session = PromptSession(**kwargs)
            except Exception:
                # Fall back to basic input if PromptSession can't be created
                # This can happen in tests or non-TTY environments
                # Catch all exceptions to ensure we always have a working fallback
                self._fallback_mode = True
                return None
        return self._session

    def get_input(self, prompt: str = "") -> str:
        """
        Get user input with history and editing support.

        Args:
            prompt: Prompt string to display

        Returns:
            User input string

        Raises:
            EOFError: When user sends EOF (Ctrl+D)
            KeyboardInterrupt: When user sends interrupt (Ctrl+C)
        """
        session = self._get_session()

        # Fallback mode: use basic stdin.readline()
        if session is None:
            try:
                # Print prompt and read from stdin
                if prompt:
                    print(prompt, end="", flush=True)
                line = sys.stdin.readline()
                if not line:
                    raise EOFError
                result = line.rstrip("\n")
                # Rotate history after successful input
                self.history_manager.rotate_history()
                return result
            except (EOFError, KeyboardInterrupt):
                # Rotate history even on interrupt/EOF
                self.history_manager.rotate_history()
                raise

        # Normal mode: use PromptSession
        try:
            # Format prompt for prompt_toolkit (handles ANSI codes properly)
            formatted_prompt = _format_prompt_for_toolkit(prompt)
            result = session.prompt(formatted_prompt)
            # Rotate history after successful input
            self.history_manager.rotate_history()
            return result
        except (EOFError, KeyboardInterrupt):
            # Rotate history even on interrupt/EOF
            self.history_manager.rotate_history()
            raise

    def cleanup(self) -> None:
        """Cleanup resources and rotate history one final time."""
        self.history_manager.rotate_history()
