# Input History Feature

This document describes the new input history functionality added to the agent CLI.

## Enhanced User Experience

The input prompt now includes helpful hints showing available navigation options:

```
Send ↵  •  ↑↓ History  •  ←→ Edit  •  /status  •  /compact  •  ESC Interrupt  •  Quit Ctrl+C
Tokens 0/180000  •  100% Context left

You ▸ _
```

## Features

### 1. Command History with Arrow Keys
- **Up/Down arrows (↑↓)**: Navigate through previous commands
- **Ctrl+R**: Search through command history (prompt_toolkit built-in)
- History is persistent across sessions
- **Hint shown in menu**: `↑↓ History`

### 2. Inline Editing
- **Left/Right arrows (←→)**: Move cursor within the input line
- **Home/End**: Jump to beginning/end of line
- **Ctrl+A/E**: Alternative shortcuts for Home/End (Unix-style)
- **Backspace/Delete**: Edit text at cursor position
- **Hint shown in menu**: `←→ Edit`

### 3. Interrupt Options
- **ESC key**: Pause the agent mid-execution to provide guidance
- **Ctrl+C**: Quit the agent gracefully
- **Ctrl+D**: Exit via EOF (alternative to Ctrl+C)
- **Hints shown in menu**: `ESC Interrupt` and `Quit Ctrl+C`

### 4. Large Paste Support
- Automatically handles large pasted content (tested up to 1000+ lines)
- No special key combinations needed - just paste
- Content is processed as-is without truncation

### 5. History Management
- History stored in `~/.indubitably-code/history.txt`
- Automatically limited to last 100 commands
- Rotation happens after each input
- Survives crashes and interrupts

## Implementation Details

### Components

1. **HistoryManager** (`input_handler.py`)
   - Manages history file creation and rotation
   - Handles edge cases (permissions, unicode errors, missing files)
   - Configurable history size (default: 100 entries)

2. **InputHandler** (`input_handler.py`)
   - Wraps prompt_toolkit's PromptSession
   - Falls back to basic stdin.readline() for non-TTY environments (tests)
   - Automatic history rotation on input/cleanup

3. **Integration with agent.py**
   - Replaces `sys.stdin.readline()` with `InputHandler.get_input()`
   - Cleanup called in finally block to ensure history rotation
   - Fully backward compatible

### Fallback Behavior

When running in non-TTY environments (e.g., tests, pipes):
- Automatically falls back to basic `sys.stdin.readline()`
- No history features available in fallback mode
- No errors or warnings - seamless degradation

## Testing

### Unit Tests
```bash
uv run pytest tests/test_input_handler.py -v
```

### Integration Tests
```bash
uv run pytest tests/integration/test_input_history_integration.py -v
```

### Manual Testing
```bash
uv run agent.py
```

You should see the enhanced menu:
```
Send ↵  •  ↑↓ History  •  ←→ Edit  •  /status  •  /compact  •  ESC Interrupt  •  Quit Ctrl+C
```

Then try:
- Type some commands and press Enter
- Press **Up arrow (↑)** to see previous commands
- Press **Left/Right arrows (←→)** to edit within the line
- Press **ESC** while the agent is thinking to interrupt
- Press **Ctrl+D** to exit
- Run again - your history should be preserved in `~/.indubitably-code/history.txt`
- Paste a large block of text - it should work seamlessly

## Dependencies

- **prompt_toolkit** (>=3.0.36): BSD-3-Clause licensed
  - Industry standard for Python CLI input
  - Used by IPython, ptpython, and many other projects
  - Full cross-platform support (Windows, Linux, macOS)

## Configuration

The history location can be customized by modifying the `DEFAULT_HISTORY_FILE` constant in `input_handler.py`:

```python
DEFAULT_HISTORY_FILE = Path.home() / ".indubitably-code" / "history.txt"
```

The maximum number of history entries can be adjusted:

```python
MAX_HISTORY_ENTRIES = 100  # Change this value
```

## Future Enhancements

Possible improvements:
- Custom keybindings configuration
- Multi-line input mode toggle
- Syntax highlighting for code blocks
- Auto-completion based on history
- Search history by prefix (like fish shell)
