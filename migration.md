# Migration Guide: Indubitably-Code → Production-Ready Architecture

**Goal**: Transform indubitably-code into a robust, enterprise-grade coding assistant by adopting architectural patterns and best practices from the mature codex-rs Rust codebase.

**Date**: 2025-10-10
**Status**: Implementation Roadmap

---

## Executive Summary

The indubitably-code project is a functional Python-based coding assistant with decent tool support. However, the codex-rs codebase demonstrates enterprise-level patterns that would significantly improve robustness, maintainability, and extensibility. This guide provides a comprehensive migration plan to adopt these patterns.

### Key Improvements to Achieve

1. **Modular Tool Architecture** - Registry/handler pattern for extensibility
2. **Type Safety & Validation** - Pydantic models for all tool schemas
3. **Parallel Tool Execution** - Concurrent tool calls with proper coordination
4. **Output Management** - Sophisticated truncation for model consumption
5. **Error Handling** - Clear fatal vs recoverable error distinction
6. **Observability** - OTEL-style telemetry and event tracking
7. **Testing Infrastructure** - Comprehensive test harness for tools
8. **MCP Integration** - Dynamic tool discovery from external servers
9. **Execution Context** - Proper sandboxing and approval policies
10. **Session Management** - Better turn tracking and diff management

---

## Current State Analysis

### Strengths of indubitably-code
- ✅ Working tool implementations
- ✅ Context management with compaction
- ✅ Session history and transcript support
- ✅ Headless CLI for automation
- ✅ Decent error handling
- ✅ MCP tool integration (AWS, Playwright)

### Gaps Compared to codex-rs
- ❌ Tools defined as simple functions, not classes
- ❌ No tool registry/router pattern
- ❌ Sequential tool execution only (no parallelism)
- ❌ Limited output truncation strategy
- ❌ No turn-level diff tracking
- ❌ Missing sandbox/approval policy integration
- ❌ No OTEL-style observability
- ❌ Tool schemas defined as plain dicts
- ❌ No tool handler trait/protocol
- ❌ Limited test coverage for tool execution

---

## Phase 1: Foundation - Tool Architecture Refactor

### 1.1 Create Tool Handler Protocol

**File**: `tools/handler.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Protocol
from enum import Enum
from dataclasses import dataclass

class ToolKind(Enum):
    """Types of tools supported by the system."""
    FUNCTION = "function"
    UNIFIED_EXEC = "unified_exec"
    MCP = "mcp"
    CUSTOM = "custom"

@dataclass
class ToolInvocation:
    """Context for a single tool invocation."""
    session: Any  # Will be properly typed later
    turn_context: Any
    tracker: Any  # TurnDiffTracker
    sub_id: str
    call_id: str
    tool_name: str
    payload: "ToolPayload"

@dataclass
class ToolOutput:
    """Result of tool execution."""
    content: str
    success: bool
    metadata: Dict[str, Any] | None = None

    def log_preview(self, max_bytes: int = 2048, max_lines: int = 64) -> str:
        """Generate truncated preview for telemetry."""
        lines = self.content.split('\n')
        if len(lines) <= max_lines and len(self.content) <= max_bytes:
            return self.content

        preview_lines = lines[:max_lines]
        preview = '\n'.join(preview_lines)
        if len(preview) > max_bytes:
            preview = preview[:max_bytes]

        if len(preview) < len(self.content):
            preview += "\n[... truncated for telemetry ...]"
        return preview

class ToolHandler(Protocol):
    """Protocol that all tool handlers must implement."""

    @property
    def kind(self) -> ToolKind:
        """Return the kind of tool this handler processes."""
        ...

    def matches_kind(self, payload: "ToolPayload") -> bool:
        """Check if this handler can process the given payload."""
        ...

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute the tool and return the result."""
        ...
```

**Migration Impact**: Medium - Requires refactoring all existing tool functions

**Benefits**:
- Clear separation of concerns
- Easier to test individual handlers
- Supports multiple payload types
- Enables parallel execution patterns

---

### 1.2 Create Tool Registry

**File**: `tools/registry.py`

```python
from typing import Dict, Optional
from dataclasses import dataclass
from tools.handler import ToolHandler, ToolInvocation, ToolOutput
from tools.spec import ToolSpec

@dataclass
class ConfiguredToolSpec:
    """Tool specification with execution configuration."""
    spec: ToolSpec
    supports_parallel: bool = False

class ToolRegistry:
    """Central registry mapping tool names to handlers."""

    def __init__(self, handlers: Dict[str, ToolHandler]):
        self.handlers = handlers

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        """Retrieve handler for a given tool name."""
        return self.handlers.get(name)

    async def dispatch(
        self,
        invocation: ToolInvocation,
    ) -> ToolOutput:
        """
        Dispatch a tool invocation to the appropriate handler.

        Handles:
        - Handler lookup
        - Payload validation
        - Error wrapping
        - Telemetry logging
        """
        handler = self.get_handler(invocation.tool_name)

        if handler is None:
            return ToolOutput(
                content=f"tool '{invocation.tool_name}' not found",
                success=False,
            )

        if not handler.matches_kind(invocation.payload):
            return ToolOutput(
                content=f"tool '{invocation.tool_name}' received incompatible payload",
                success=False,
            )

        # Execute with telemetry
        start = time.time()
        try:
            output = await handler.handle(invocation)
            duration = time.time() - start

            # Log to telemetry
            if hasattr(invocation.turn_context, 'telemetry'):
                invocation.turn_context.telemetry.record_tool_execution(
                    tool_name=invocation.tool_name,
                    duration=duration,
                    success=output.success,
                )

            return output
        except Exception as exc:
            duration = time.time() - start

            # Log error to telemetry
            if hasattr(invocation.turn_context, 'telemetry'):
                invocation.turn_context.telemetry.record_tool_execution(
                    tool_name=invocation.tool_name,
                    duration=duration,
                    success=False,
                    error=str(exc),
                )

            return ToolOutput(
                content=f"tool execution failed: {exc}",
                success=False,
            )

class ToolRegistryBuilder:
    """Builder for constructing tool registries."""

    def __init__(self):
        self.handlers: Dict[str, ToolHandler] = {}
        self.specs: List[ConfiguredToolSpec] = []

    def register_handler(self, name: str, handler: ToolHandler) -> None:
        """Register a handler for a tool name."""
        if name in self.handlers:
            print(f"Warning: overwriting handler for tool {name}", file=sys.stderr)
        self.handlers[name] = handler

    def add_spec(self, spec: ToolSpec, supports_parallel: bool = False) -> None:
        """Add a tool specification."""
        self.specs.append(ConfiguredToolSpec(spec, supports_parallel))

    def build(self) -> tuple[list[ConfiguredToolSpec], ToolRegistry]:
        """Build the final registry and spec list."""
        return self.specs, ToolRegistry(self.handlers)
```

**Migration Impact**: High - Core architectural change

**Benefits**:
- Centralized tool management
- Easy to add/remove tools dynamically
- Supports MCP tool discovery
- Enables testing with mock handlers

---

### 1.3 Create Tool Router

**File**: `tools/router.py`

```python
from typing import Optional
from dataclasses import dataclass
from tools.registry import ToolRegistry, ConfiguredToolSpec
from tools.handler import ToolInvocation, ToolPayload

@dataclass
class ToolCall:
    """Represents a tool call from the model."""
    tool_name: str
    call_id: str
    payload: ToolPayload

class ToolRouter:
    """Routes tool calls to appropriate handlers via the registry."""

    def __init__(self, registry: ToolRegistry, specs: list[ConfiguredToolSpec]):
        self.registry = registry
        self.specs = specs

    def tool_supports_parallel(self, tool_name: str) -> bool:
        """Check if a tool supports parallel execution."""
        for spec in self.specs:
            if spec.spec.name == tool_name:
                return spec.supports_parallel
        return False

    @staticmethod
    def build_tool_call(item: Dict[str, Any]) -> Optional[ToolCall]:
        """
        Parse a response block into a ToolCall.

        Handles:
        - FunctionCall blocks
        - CustomToolCall blocks
        - LocalShellCall blocks
        - MCP tool calls
        """
        item_type = item.get("type")

        if item_type == "tool_use":
            name = item.get("name", "")
            call_id = item.get("id", "")
            arguments = item.get("input", {})

            # Check if it's an MCP tool (has server prefix)
            if "/" in name:
                server, tool = name.split("/", 1)
                payload = ToolPayload.mcp(server, tool, arguments)
            else:
                payload = ToolPayload.function(arguments)

            return ToolCall(
                tool_name=name,
                call_id=call_id,
                payload=payload,
            )

        return None

    async def dispatch_tool_call(
        self,
        session: Any,
        turn_context: Any,
        tracker: Any,
        sub_id: str,
        call: ToolCall,
    ) -> Dict[str, Any]:
        """
        Dispatch a tool call through the registry.

        Returns a tool_result block suitable for the conversation.
        """
        invocation = ToolInvocation(
            session=session,
            turn_context=turn_context,
            tracker=tracker,
            sub_id=sub_id,
            call_id=call.call_id,
            tool_name=call.tool_name,
            payload=call.payload,
        )

        output = await self.registry.dispatch(invocation)

        return {
            "type": "tool_result",
            "tool_use_id": call.call_id,
            "content": output.content,
            "is_error": not output.success,
        }
```

**Migration Impact**: High - Requires agent.py refactor

**Benefits**:
- Clean separation of routing logic
- Supports multiple tool call formats
- Easy to extend for new payload types
- Foundation for parallel execution

---

## Phase 2: Type Safety & Validation

### 2.1 Introduce Pydantic Models for Tool Schemas

**File**: `tools/schemas.py`

```python
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, Literal
from enum import Enum

class ToolSchema(BaseModel):
    """Base class for all tool input schemas."""

    class Config:
        extra = "forbid"  # Reject unknown fields
        validate_assignment = True

class EditFileInput(ToolSchema):
    """Validated input for edit_file tool."""
    path: str = Field(..., min_length=1, description="Path to the file")
    old_str: str = Field(..., description="Exact text to replace")
    new_str: str = Field(..., description="Replacement text")
    dry_run: bool = Field(False, description="Preview without writing")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Ensure path doesn't contain dangerous patterns."""
        if ".." in v or v.startswith("/etc"):
            raise ValueError("path contains suspicious patterns")
        return v

    @field_validator("old_str", "new_str")
    @classmethod
    def validate_strings_differ(cls, v: str, info) -> str:
        """Ensure old and new strings are different."""
        values = info.data
        if "old_str" in values and values.get("old_str") == v and info.field_name == "new_str":
            raise ValueError("old_str and new_str must be different")
        return v

class RunTerminalCmdInput(ToolSchema):
    """Validated input for run_terminal_cmd tool."""
    command: str = Field(..., min_length=1)
    is_background: bool = Field(False)
    explanation: Optional[str] = None
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: Optional[float] = Field(None, ge=0)
    stdin: Optional[str] = None
    shell: Optional[str] = None

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Basic command safety checks."""
        dangerous = ["rm -rf /", "dd if=", ":(){ :|:& };:"]
        if any(d in v for d in dangerous):
            raise ValueError("command contains dangerous patterns")
        return v

    @field_validator("stdin")
    @classmethod
    def validate_stdin_usage(cls, v: Optional[str], info) -> Optional[str]:
        """Ensure stdin not used with background jobs."""
        values = info.data
        if v is not None and values.get("is_background"):
            raise ValueError("stdin not supported with background jobs")
        return v

class GrepInput(ToolSchema):
    """Validated input for grep tool."""
    pattern: str = Field(..., min_length=1)
    path: str = Field(".", description="Directory to search")
    include: Optional[str] = Field(None, description="Glob pattern for files")
    context_lines: int = Field(0, ge=0, le=10)
    case_insensitive: bool = False
    max_results: int = Field(100, ge=1, le=1000)
```

**Migration Steps**:

1. **Convert all tool input dicts to Pydantic models**
   - Create schema classes for each tool
   - Add validators for business logic
   - Include field documentation

2. **Update tool implementations**
   ```python
   # Before
   def edit_file_impl(input: Dict[str, Any]) -> str:
       path = input.get("path", "")
       old = input.get("old_str", None)
       # ...

   # After
   def edit_file_impl(input: EditFileInput) -> str:
       # Input already validated
       path = input.path
       old = input.old_str
       # ...
   ```

3. **Add validation wrapper**
   ```python
   def validate_tool_input(schema: type[ToolSchema], raw_input: Dict[str, Any]) -> ToolSchema:
       """Validate and parse tool input."""
       try:
           return schema(**raw_input)
       except ValidationError as exc:
           errors = []
           for error in exc.errors():
                field = ".".join(str(x) for x in error["loc"])
               errors.append(f"{field}: {error['msg']}")
           raise ValueError(f"Invalid input: {'; '.join(errors)}")
   ```

**Migration Impact**: Medium - Touch all tool files

**Benefits**:
- Catch errors before execution
- Self-documenting schemas
- IDE autocomplete support
- Consistent validation logic

---

## Phase 3: Parallel Tool Execution

### 3.1 Implement Tool Call Runtime

**File**: `tools/parallel.py`

```python
import asyncio
from typing import Any, Dict
from dataclasses import dataclass
from tools.router import ToolRouter, ToolCall
from tools.handler import ToolInvocation

@dataclass
class ToolCallRuntime:
    """Manages parallel tool execution with proper coordination."""

    router: ToolRouter
    session: Any
    turn_context: Any
    tracker: Any
    sub_id: str
    _lock: asyncio.RWLock  # Simulated with asyncio.Lock and counter

    async def execute_tool_call(self, call: ToolCall) -> Dict[str, Any]:
        """
        Execute a tool call with appropriate locking.

        - Parallel tools: acquire read lock (multiple can run)
        - Sequential tools: acquire write lock (exclusive)
        """
        supports_parallel = self.router.tool_supports_parallel(call.tool_name)

        if supports_parallel:
            # Acquire read lock - allows multiple parallel tools
            async with self._read_lock():
                return await self.router.dispatch_tool_call(
                    self.session,
                    self.turn_context,
                    self.tracker,
                    self.sub_id,
                    call,
                )
        else:
            # Acquire write lock - exclusive access
            async with self._write_lock():
                return await self.router.dispatch_tool_call(
                    self.session,
                    self.turn_context,
                    self.tracker,
                    self.sub_id,
                    call,
                )

    # RWLock simulation (Python lacks built-in RWLock)
    def __post_init__(self):
        self._readers = 0
        self._writer = False
        self._read_lock_obj = asyncio.Lock()
        self._write_lock_obj = asyncio.Lock()

    async def _read_lock(self):
        """Acquire read lock (shared)."""
        return _ReadLock(self)

    async def _write_lock(self):
        """Acquire write lock (exclusive)."""
        return _WriteLock(self)

class _ReadLock:
    """Context manager for read locks."""
    def __init__(self, runtime: ToolCallRuntime):
        self.runtime = runtime

    async def __aenter__(self):
        async with self.runtime._read_lock_obj:
            while self.runtime._writer:
                await asyncio.sleep(0.01)
            self.runtime._readers += 1

    async def __aexit__(self, *args):
        async with self.runtime._read_lock_obj:
            self.runtime._readers -= 1

class _WriteLock:
    """Context manager for write locks."""
    def __init__(self, runtime: ToolCallRuntime):
        self.runtime = runtime

    async def __aenter__(self):
        async with self.runtime._write_lock_obj:
            while self.runtime._readers > 0 or self.runtime._writer:
                await asyncio.sleep(0.01)
            self.runtime._writer = True

    async def __aexit__(self, *args):
        self.runtime._writer = False
```

### 3.2 Update Agent to Use Async Tool Execution

**File**: `agent.py` (modifications)

```python
# Add at top
import asyncio

async def _execute_tools_parallel(
    runtime: ToolCallRuntime,
    tool_calls: list[ToolCall],
) -> list[Dict[str, Any]]:
    """Execute multiple tool calls, respecting parallelism."""
    tasks = [runtime.execute_tool_call(call) for call in tool_calls]
    return await asyncio.gather(*tasks)

# In run_agent function, replace tool execution:
def run_agent(tools, **kwargs):
    # ... setup code ...

    # Create runtime
    runtime = ToolCallRuntime(
        router=tool_router,
        session=session,
        turn_context=turn_context,
        tracker=diff_tracker,
        sub_id=sub_id,
    )

    # ... in message loop ...

    # Collect all tool_use blocks
    tool_calls = []
    for block in assistant_blocks:
        if block.get("type") == "tool_use":
            call = ToolRouter.build_tool_call(block)
            if call:
                tool_calls.append(call)

    # Execute all tools (potentially in parallel)
    if tool_calls:
        tool_results = asyncio.run(
            _execute_tools_parallel(runtime, tool_calls)
        )
        context.add_tool_results(tool_results, dedupe=False)
```

**Migration Impact**: High - Requires async refactor

**Benefits**:
- Massive speedup for multiple tool calls
- Proper coordination prevents conflicts
- Maintains sequential ordering where needed
- Foundation for streaming tool execution

---

## Phase 4: Output Management & Truncation

### 4.1 Implement Smart Output Formatting

**File**: `tools/output.py`

```python
from typing import Optional
from dataclasses import dataclass

# Constants from codex-rs
MODEL_FORMAT_MAX_BYTES = 10 * 1024  # 10 KiB
MODEL_FORMAT_MAX_LINES = 256
MODEL_FORMAT_HEAD_LINES = 128
MODEL_FORMAT_TAIL_LINES = 128
MODEL_FORMAT_HEAD_BYTES = 5 * 1024

@dataclass
class ExecOutput:
    """Structured output from command execution."""
    exit_code: int
    duration_seconds: float
    output: str
    timed_out: bool = False

def format_exec_output(output: ExecOutput) -> str:
    """
    Format exec output for model consumption with intelligent truncation.

    Strategy:
    - Full output if under limits
    - Head+tail with elision marker if over limits
    - Line and byte limits respected
    - Metadata included
    """
    content = output.output

    if output.timed_out:
        content = f"command timed out after {output.duration_seconds}s\n{content}"

    total_lines = content.count('\n') + 1

    # Check if truncation needed
    if len(content) <= MODEL_FORMAT_MAX_BYTES and total_lines <= MODEL_FORMAT_MAX_LINES:
        return _format_output_json(output, content)

    # Truncate with head+tail
    truncated = _truncate_head_tail(content, total_lines)
    summary = f"Total output lines: {total_lines}\n\n{truncated}"

    return _format_output_json(output, summary)

def _truncate_head_tail(content: str, total_lines: int) -> str:
    """
    Truncate content showing head and tail with elision marker.

    Matches codex-rs behavior:
    - Split by lines
    - Take first N lines (head)
    - Take last N lines (tail)
    - Add marker in between
    - Respect byte limits
    """
    lines = content.split('\n')

    head_lines = lines[:MODEL_FORMAT_HEAD_LINES]
    tail_lines = lines[-MODEL_FORMAT_TAIL_LINES:] if len(lines) > MODEL_FORMAT_HEAD_LINES else []

    omitted = max(0, total_lines - MODEL_FORMAT_HEAD_LINES - MODEL_FORMAT_TAIL_LINES)

    head_text = '\n'.join(head_lines)
    tail_text = '\n'.join(tail_lines)
    marker = f"\n[... omitted {omitted} of {total_lines} lines ...]\n\n"

    # Respect byte budget
    head_budget = MODEL_FORMAT_HEAD_BYTES
    tail_budget = MODEL_FORMAT_MAX_BYTES - head_budget - len(marker)

    if len(head_text) > head_budget:
        head_text = head_text[:head_budget]
        # Find last complete line
        last_newline = head_text.rfind('\n')
        if last_newline > 0:
            head_text = head_text[:last_newline]

    result = head_text + marker

    remaining_budget = MODEL_FORMAT_MAX_BYTES - len(result)
    if remaining_budget > 0 and tail_text:
        if len(tail_text) > remaining_budget:
            # Take from end
            tail_text = tail_text[-remaining_budget:]
            # Find first complete line
            first_newline = tail_text.find('\n')
            if first_newline > 0:
                tail_text = tail_text[first_newline + 1:]
        result += tail_text

    return result

def _format_output_json(output: ExecOutput, content: str) -> str:
    """Format output as JSON with metadata."""
    import json

    return json.dumps({
        "output": content,
        "metadata": {
            "exit_code": output.exit_code,
            "duration_seconds": round(output.duration_seconds, 1),
        }
    }, ensure_ascii=False)
```

### 4.2 Update Terminal Command Tool

**File**: `tools_run_terminal_cmd.py` (modifications)

```python
from tools.output import format_exec_output, ExecOutput
import time

def _run_foreground(command, cwd, env, shell_executable, timeout, stdin_data):
    start = time.time()

    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable=shell_executable,
            capture_output=True,
            text=True,
            env=_merge_env(env),
            cwd=cwd or None,
            timeout=timeout,
            input=stdin_data,
        )

        duration = time.time() - start
        output = ExecOutput(
            exit_code=completed.returncode,
            duration_seconds=duration,
            output=completed.stdout + completed.stderr,
            timed_out=False,
        )

        return format_exec_output(output)

    except subprocess.TimeoutExpired as exc:
        duration = time.time() - start
        output = ExecOutput(
            exit_code=-1,
            duration_seconds=duration,
            output=(exc.stdout or "") + (exc.stderr or ""),
            timed_out=True,
        )

        return format_exec_output(output)
```

**Migration Impact**: Medium - Update tool implementations

**Benefits**:
- Prevents context window bloat
- Shows most relevant output (beginning + end)
- Maintains full output in logs
- Consistent with codex-rs behavior

---

## Phase 5: Turn Diff Tracking

### 5.1 Create Turn Diff Tracker

**File**: `session/turn_diff_tracker.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, Optional
from datetime import datetime

@dataclass
class FileEdit:
    """Represents an edit to a file during a turn."""
    path: Path
    tool_name: str
    timestamp: datetime
    action: str  # "create", "edit", "delete", "rename"
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None

@dataclass
class TurnDiffTracker:
    """
    Tracks all file modifications during a single turn.

    Purpose:
    - Provide undo capability
    - Generate diffs for review
    - Track dependencies between tools
    - Prevent conflicting edits
    """
    turn_id: int
    edits: list[FileEdit] = field(default_factory=list)
    _edited_paths: Set[Path] = field(default_factory=set)
    _locked_paths: Set[Path] = field(default_factory=set)

    def record_edit(
        self,
        path: str | Path,
        tool_name: str,
        action: str,
        *,
        old_content: Optional[str] = None,
        new_content: Optional[str] = None,
        line_range: Optional[tuple[int, int]] = None,
    ) -> None:
        """Record a file edit."""
        path = Path(path).resolve()

        if path in self._locked_paths:
            raise ValueError(f"File {path} is locked by another operation")

        edit = FileEdit(
            path=path,
            tool_name=tool_name,
            timestamp=datetime.now(),
            action=action,
            old_content=old_content,
            new_content=new_content,
            line_range=line_range,
        )

        self.edits.append(edit)
        self._edited_paths.add(path)

    def lock_file(self, path: str | Path) -> None:
        """Lock a file to prevent concurrent edits."""
        self._locked_paths.add(Path(path).resolve())

    def unlock_file(self, path: str | Path) -> None:
        """Unlock a file."""
        self._locked_paths.discard(Path(path).resolve())

    def get_edits_for_path(self, path: str | Path) -> list[FileEdit]:
        """Get all edits for a specific file."""
        path = Path(path).resolve()
        return [edit for edit in self.edits if edit.path == path]

    def generate_summary(self) -> str:
        """Generate a human-readable summary of changes."""
        if not self.edits:
            return "No files modified this turn."

        summary_lines = [f"Turn {self.turn_id} modifications:"]

        # Group by path
        by_path: Dict[Path, list[FileEdit]] = {}
        for edit in self.edits:
            by_path.setdefault(edit.path, []).append(edit)

        for path, edits in sorted(by_path.items()):
            actions = ", ".join(e.action for e in edits)
            tools = ", ".join(set(e.tool_name for e in edits))
            summary_lines.append(f"  {path}: {actions} (via {tools})")

        return "\n".join(summary_lines)

    def generate_unified_diff(self) -> Optional[str]:
        """Generate unified diff for all edits."""
        import difflib

        diffs = []

        for path in sorted(self._edited_paths):
            path_edits = self.get_edits_for_path(path)
            if not path_edits:
                continue

            # Find first edit with old_content and last edit with new_content
            old_content = None
            new_content = None

            for edit in path_edits:
                if old_content is None and edit.old_content is not None:
                    old_content = edit.old_content
                if edit.new_content is not None:
                    new_content = edit.new_content

            if old_content is not None and new_content is not None:
                diff = difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    lineterm="",
                )
                diffs.append("".join(diff))

        return "\n".join(diffs) if diffs else None
```

### 5.2 Integrate with Tools

**Example**: Update `edit_file_impl` to track changes

```python
def edit_file_impl(input: EditFileInput, tracker: TurnDiffTracker) -> str:
    """Edit file with diff tracking."""
    path = Path(input.path)

    # Lock file during edit
    tracker.lock_file(path)

    try:
        # Read old content
        old_content = None
        if path.exists():
            old_content = path.read_text(encoding="utf-8")

        # Perform edit (existing logic)
        # ...

        # Read new content
        new_content = path.read_text(encoding="utf-8")

        # Record the edit
        tracker.record_edit(
            path=path,
            tool_name="edit_file",
            action="edit" if old_content else "create",
            old_content=old_content,
            new_content=new_content,
        )

        return json.dumps({"ok": True, "path": str(path)})

    finally:
        tracker.unlock_file(path)
```

**Migration Impact**: Medium - Update tool signatures

**Benefits**:
- Undo capability
- Conflict detection
- Audit trail
- Diff generation for review

---

## Phase 6: Error Handling & Observability

### 6.1 Structured Error Types

**File**: `errors.py`

```python
from enum import Enum

class ErrorType(Enum):
    """Classification of errors for handling strategy."""
    FATAL = "fatal"  # Stop execution, escalate
    RECOVERABLE = "recoverable"  # Return to model for retry
    VALIDATION = "validation"  # Input validation failed

class ToolError(Exception):
    """Base exception for tool execution errors."""

    def __init__(self, message: str, error_type: ErrorType = ErrorType.RECOVERABLE):
        super().__init__(message)
        self.message = message
        self.error_type = error_type

class FatalToolError(ToolError):
    """Error that should stop agent execution."""

    def __init__(self, message: str):
        super().__init__(message, ErrorType.FATAL)

class ValidationError(ToolError):
    """Input validation failed."""

    def __init__(self, message: str):
        super().__init__(message, ErrorType.VALIDATION)

class SandboxError(ToolError):
    """Sandbox policy violation."""

    def __init__(self, message: str):
        super().__init__(message, ErrorType.FATAL)
```

### 6.2 Telemetry Enhancement

**File**: `session/telemetry.py` (enhancements)

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import json

@dataclass
class ToolExecutionEvent:
    """Detailed tool execution telemetry."""
    tool_name: str
    call_id: str
    turn: int
    timestamp: datetime
    duration: float
    success: bool
    error: Optional[str] = None
    input_size: int = 0
    output_size: int = 0
    truncated: bool = False

@dataclass
class TelemetryCollector:
    """Enhanced telemetry collection."""

    # Existing fields
    token_usage: int = 0
    compaction_events: int = 0
    # ... existing fields ...

    # New fields
    tool_executions: List[ToolExecutionEvent] = field(default_factory=list)
    tool_execution_times: Dict[str, List[float]] = field(default_factory=dict)
    tool_error_counts: Dict[str, int] = field(default_factory=dict)
    parallel_tool_batches: int = 0

    def record_tool_execution(
        self,
        tool_name: str,
        call_id: str,
        turn: int,
        duration: float,
        success: bool,
        error: Optional[str] = None,
        input_size: int = 0,
        output_size: int = 0,
        truncated: bool = False,
    ) -> None:
        """Record a tool execution event."""
        event = ToolExecutionEvent(
            tool_name=tool_name,
            call_id=call_id,
            turn=turn,
            timestamp=datetime.now(),
            duration=duration,
            success=success,
            error=error,
            input_size=input_size,
            output_size=output_size,
            truncated=truncated,
        )

        self.tool_executions.append(event)

        # Update aggregates
        self.tool_execution_times.setdefault(tool_name, []).append(duration)

        if not success:
            self.tool_error_counts[tool_name] = self.tool_error_counts.get(tool_name, 0) + 1

    def get_tool_stats(self, tool_name: str) -> Dict[str, any]:
        """Get statistics for a specific tool."""
        times = self.tool_execution_times.get(tool_name, [])
        if not times:
            return {"calls": 0}

        return {
            "calls": len(times),
            "avg_duration": sum(times) / len(times),
            "min_duration": min(times),
            "max_duration": max(times),
            "errors": self.tool_error_counts.get(tool_name, 0),
            "success_rate": 1.0 - (self.tool_error_counts.get(tool_name, 0) / len(times)),
        }

    def export_otel_format(self) -> str:
        """Export in OTEL-compatible JSON format."""
        events = []

        for event in self.tool_executions:
            events.append({
                "timestamp": event.timestamp.isoformat(),
                "name": f"tool.{event.tool_name}",
                "attributes": {
                    "tool.name": event.tool_name,
                    "tool.call_id": event.call_id,
                    "tool.turn": event.turn,
                    "tool.duration_ms": event.duration * 1000,
                    "tool.success": event.success,
                    "tool.error": event.error,
                    "tool.input_bytes": event.input_size,
                    "tool.output_bytes": event.output_size,
                    "tool.truncated": event.truncated,
                }
            })

        return json.dumps({"events": events}, indent=2)
```

**Migration Impact**: Low - Additive change

**Benefits**:
- Detailed performance metrics
- Error tracking per tool
- OTEL compatibility for external observability platforms
- Debugging insights

---

## Phase 7: Testing Infrastructure

### 7.1 Tool Test Harness

**File**: `tests/tool_harness.py`

```python
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from tools.handler import ToolHandler, ToolInvocation, ToolOutput, ToolKind
from tools.registry import ToolRegistry
from session.turn_diff_tracker import TurnDiffTracker
from unittest.mock import Mock

@dataclass
class MockToolContext:
    """Mock context for testing tools in isolation."""

    session: Mock
    turn_context: Mock
    tracker: TurnDiffTracker
    sub_id: str = "test-sub"

    @classmethod
    def create(cls, turn_id: int = 1) -> "MockToolContext":
        """Create a mock context for testing."""
        session = Mock()
        turn_context = Mock()
        turn_context.cwd = Path.cwd()
        turn_context.telemetry = Mock()

        tracker = TurnDiffTracker(turn_id=turn_id)

        return cls(
            session=session,
            turn_context=turn_context,
            tracker=tracker,
        )

class ToolTestHarness:
    """Test harness for tool handlers."""

    def __init__(self, handler: ToolHandler, context: Optional[MockToolContext] = None):
        self.handler = handler
        self.context = context or MockToolContext.create()

    async def invoke(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        call_id: str = "test-call",
    ) -> ToolOutput:
        """Invoke a tool with test context."""
        from tools.handler import ToolPayload

        invocation = ToolInvocation(
            session=self.context.session,
            turn_context=self.context.turn_context,
            tracker=self.context.tracker,
            sub_id=self.context.sub_id,
            call_id=call_id,
            tool_name=tool_name,
            payload=ToolPayload.function(payload),
        )

        return await self.handler.handle(invocation)

    def assert_success(self, output: ToolOutput) -> None:
        """Assert that tool execution succeeded."""
        assert output.success, f"Tool failed: {output.content}"

    def assert_error(self, output: ToolOutput, expected_msg: Optional[str] = None) -> None:
        """Assert that tool execution failed."""
        assert not output.success, f"Tool should have failed but succeeded"
        if expected_msg:
            assert expected_msg in output.content, \
                f"Expected '{expected_msg}' in error, got: {output.content}"

    def get_file_edits(self, path: str) -> list:
        """Get all edits to a specific file."""
        return self.context.tracker.get_edits_for_path(path)

# Example test
@pytest.mark.asyncio
async def test_edit_file_basic():
    """Test basic file editing."""
    from tools.handlers.edit_file import EditFileHandler

    harness = ToolTestHarness(EditFileHandler())

    # Create a temp file
    tmp = Path("/tmp/test_edit.txt")
    tmp.write_text("hello world")

    try:
        # Test edit
        output = await harness.invoke(
            "edit_file",
            {
                "path": str(tmp),
                "old_str": "world",
                "new_str": "Python",
                "dry_run": False,
            }
        )

        harness.assert_success(output)

        # Verify content changed
        assert tmp.read_text() == "hello Python"

        # Verify tracking
        edits = harness.get_file_edits(str(tmp))
        assert len(edits) == 1
        assert edits[0].action == "edit"

    finally:
        tmp.unlink(missing_ok=True)
```

### 7.2 Parallel Execution Tests

**File**: `tests/test_tool_parallelism.py`

```python
import asyncio
import pytest
from tools.parallel import ToolCallRuntime
from tools.router import ToolCall, ToolRouter
from tools.handler import ToolPayload
from tests.tool_harness import MockToolContext

@pytest.mark.asyncio
async def test_parallel_tools_run_concurrently():
    """Test that parallel tools execute concurrently."""
    # Create tools that sleep for 1 second
    # If sequential: 3 seconds total
    # If parallel: ~1 second total

    context = MockToolContext.create()
    router = create_test_router_with_parallel_tools()

    runtime = ToolCallRuntime(
        router=router,
        session=context.session,
        turn_context=context.turn_context,
        tracker=context.tracker,
        sub_id="test",
    )

    calls = [
        ToolCall("sleep_tool", "call-1", ToolPayload.function({"duration": 1})),
        ToolCall("sleep_tool", "call-2", ToolPayload.function({"duration": 1})),
        ToolCall("sleep_tool", "call-3", ToolPayload.function({"duration": 1})),
    ]

    start = time.time()
    results = await asyncio.gather(*[runtime.execute_tool_call(c) for c in calls])
    elapsed = time.time() - start

    # Should complete in ~1 second (parallel), not 3 seconds (sequential)
    assert elapsed < 2.0, f"Tools ran sequentially: {elapsed}s"
    assert len(results) == 3

@pytest.mark.asyncio
async def test_sequential_tools_block_each_other():
    """Test that sequential tools execute exclusively."""
    context = MockToolContext.create()
    router = create_test_router_with_sequential_tools()

    runtime = ToolCallRuntime(
        router=router,
        session=context.session,
        turn_context=context.turn_context,
        tracker=context.tracker,
        sub_id="test",
    )

    # Track execution order
    execution_log = []

    async def tracked_edit(call):
        execution_log.append(("start", call.call_id))
        result = await runtime.execute_tool_call(call)
        execution_log.append(("end", call.call_id))
        return result

    calls = [
        ToolCall("edit_file", "call-1", ToolPayload.function({"path": "/tmp/a.txt", ...})),
        ToolCall("edit_file", "call-2", ToolPayload.function({"path": "/tmp/b.txt", ...})),
    ]

    await asyncio.gather(*[tracked_edit(c) for c in calls])

    # Verify no interleaving (one must complete before other starts)
    assert execution_log[0][0] == "start"
    assert execution_log[1][0] == "end"  # First call ends
    assert execution_log[2][0] == "start"  # Second call starts
    assert execution_log[3][0] == "end"
```

**Migration Impact**: Medium - New testing patterns

**Benefits**:
- Isolated tool testing
- Reproducible test environment
- Easy to test edge cases
- Parallel execution verification

---

## Phase 8: MCP Integration Improvements

### 8.1 Dynamic MCP Tool Discovery

**File**: `tools/mcp_integration.py`

```python
from typing import Dict, Optional
import json
from pathlib import Path

class MCPToolDiscovery:
    """Discovers and registers MCP tools from servers."""

    def __init__(self):
        self.servers: Dict[str, MCPServerConfig] = {}

    def register_server(
        self,
        name: str,
        command: str,
        args: list[str],
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register an MCP server configuration."""
        self.servers[name] = MCPServerConfig(
            name=name,
            command=command,
            args=args,
            env=env or {},
        )

    async def discover_tools(self, server_name: str) -> Dict[str, ToolSpec]:
        """
        Connect to MCP server and discover available tools.

        Returns dict mapping fully-qualified-name -> ToolSpec
        """
        if server_name not in self.servers:
            raise ValueError(f"Unknown MCP server: {server_name}")

        server = self.servers[server_name]

        # Connect to MCP server
        client = await self._connect_mcp_server(server)

        # List tools
        tools_response = await client.list_tools()

        tool_specs = {}
        for tool in tools_response.tools:
            # Convert MCP schema to our ToolSpec
            fq_name = f"{server_name}/{tool.name}"
            spec = self._convert_mcp_tool_to_spec(fq_name, tool)
            tool_specs[fq_name] = spec

        return tool_specs

    def _convert_mcp_tool_to_spec(
        self,
        fq_name: str,
        mcp_tool: Any,
    ) -> ToolSpec:
        """
        Convert MCP tool definition to our ToolSpec.

        Handles:
        - Missing "properties" field
        - "integer" type normalization to "number"
        - Missing "type" fields
        - Additional properties schemas
        """
        schema = mcp_tool.input_schema

        # Ensure properties exists (OpenAI requirement)
        if "properties" not in schema:
            schema["properties"] = {}

        # Sanitize schema recursively
        schema = self._sanitize_json_schema(schema)

        return ToolSpec(
            name=fq_name,
            description=mcp_tool.description or "",
            input_schema=schema,
        )

    def _sanitize_json_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize MCP JSON schema for compatibility.

        Based on codex-rs implementation:
        - Ensures "type" field present
        - Normalizes "integer" -> "number"
        - Adds missing "properties" for objects
        - Adds missing "items" for arrays
        """
        if not isinstance(schema, dict):
            return schema

        # Handle type field
        schema_type = schema.get("type")

        if schema_type is None:
            # Infer type from other fields
            if "properties" in schema or "additionalProperties" in schema:
                schema_type = "object"
            elif "items" in schema:
                schema_type = "array"
            elif "enum" in schema or "const" in schema:
                schema_type = "string"
            elif "minimum" in schema or "maximum" in schema:
                schema_type = "number"
            else:
                schema_type = "string"  # Default

            schema["type"] = schema_type

        # Normalize integer -> number
        if schema_type == "integer":
            schema["type"] = "number"

        # Ensure object has properties
        if schema_type == "object" and "properties" not in schema:
            schema["properties"] = {}

        # Ensure array has items
        if schema_type == "array" and "items" not in schema:
            schema["items"] = {"type": "string"}

        # Recursively sanitize nested schemas
        if "properties" in schema:
            for key, prop_schema in schema["properties"].items():
                schema["properties"][key] = self._sanitize_json_schema(prop_schema)

        if "items" in schema:
            schema["items"] = self._sanitize_json_schema(schema["items"])

        if isinstance(schema.get("additionalProperties"), dict):
            schema["additionalProperties"] = self._sanitize_json_schema(
                schema["additionalProperties"]
            )

        return schema
```

### 8.2 MCP Tool Handler

**File**: `tools/handlers/mcp_handler.py`

```python
from tools.handler import ToolHandler, ToolInvocation, ToolOutput, ToolKind

class MCPHandler(ToolHandler):
    """Handler that delegates to MCP servers."""

    @property
    def kind(self) -> ToolKind:
        return ToolKind.MCP

    def matches_kind(self, payload: ToolPayload) -> bool:
        return isinstance(payload, MCPToolPayload)

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute MCP tool call."""
        if not isinstance(invocation.payload, MCPToolPayload):
            return ToolOutput(
                content="MCP handler received non-MCP payload",
                success=False,
            )

        server = invocation.payload.server
        tool = invocation.payload.tool
        arguments = invocation.payload.arguments

        # Get MCP client for server
        client = await invocation.session.get_mcp_client(server)

        if client is None:
            return ToolOutput(
                content=f"MCP server '{server}' not available",
                success=False,
            )

        # Call tool on MCP server
        try:
            result = await client.call_tool(tool, arguments)

            # MCP returns CallToolResult with content array
            content_parts = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_parts.append(item.text)

            output_text = "\n".join(content_parts)

            return ToolOutput(
                content=output_text,
                success=not result.isError,
            )

        except Exception as exc:
            return ToolOutput(
                content=f"MCP tool call failed: {exc}",
                success=False,
            )
```

**Migration Impact**: Low - Extends existing MCP support

**Benefits**:
- Automatic tool discovery
- Schema validation
- Unified interface
- Better error handling

---

## Phase 9: Configuration & Policies

### 9.1 Execution Policies

**File**: `policies.py`

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class SandboxPolicy(Enum):
    """Sandbox restriction levels."""
    NONE = "none"  # No restrictions
    RESTRICTED = "restricted"  # Common restrictions
    STRICT = "strict"  # Minimal permissions

class ApprovalPolicy(Enum):
    """When to request user approval."""
    NEVER = "never"  # Auto-approve all
    ON_REQUEST = "on_request"  # Only when tool requests
    ON_WRITE = "on_write"  # Any filesystem write
    ALWAYS = "always"  # Every tool call

@dataclass
class ExecutionContext:
    """Context for tool execution with policies."""

    cwd: Path
    sandbox_policy: SandboxPolicy
    approval_policy: ApprovalPolicy
    allowed_paths: list[Path] | None = None
    blocked_commands: list[str] | None = None
    timeout_seconds: float | None = None

    def can_execute_command(self, command: str) -> tuple[bool, Optional[str]]:
        """Check if command is allowed."""
        if self.blocked_commands:
            for blocked in self.blocked_commands:
                if blocked in command:
                    return False, f"Command contains blocked pattern: {blocked}"

        if self.sandbox_policy == SandboxPolicy.STRICT:
            # Only allow specific safe commands
            safe_commands = ["ls", "cat", "echo", "pwd", "grep"]
            first_token = command.split()[0] if command.split() else ""
            if first_token not in safe_commands:
                return False, f"Command '{first_token}' not allowed in strict mode"

        return True, None

    def can_write_path(self, path: Path) -> tuple[bool, Optional[str]]:
        """Check if path can be written."""
        path = path.resolve()

        if self.allowed_paths:
            # Check if path is under any allowed path
            allowed = False
            for allowed_path in self.allowed_paths:
                try:
                    path.relative_to(allowed_path)
                    allowed = True
                    break
                except ValueError:
                    continue

            if not allowed:
                return False, f"Path {path} not under allowed paths"

        # Block system paths
        system_paths = ["/etc", "/sys", "/proc", "/dev"]
        for system_path in system_paths:
            try:
                path.relative_to(system_path)
                return False, f"Cannot write to system path {system_path}"
            except ValueError:
                continue

        return True, None

    def requires_approval(self, tool_name: str, is_write: bool) -> bool:
        """Check if tool call requires user approval."""
        if self.approval_policy == ApprovalPolicy.ALWAYS:
            return True
        elif self.approval_policy == ApprovalPolicy.ON_WRITE:
            return is_write
        elif self.approval_policy == ApprovalPolicy.ON_REQUEST:
            # Tool must explicitly request approval
            return False
        else:  # NEVER
            return False
```

### 9.2 Tool Execution with Policies

**File**: `tools/handlers/shell_handler.py`

```python
from tools.handler import ToolHandler, ToolInvocation, ToolOutput
from policies import ExecutionContext

class ShellHandler(ToolHandler):
    """Handler for shell command execution."""

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute shell command with policy checks."""
        command = invocation.payload.get("command", "")

        # Get execution context from turn context
        exec_context: ExecutionContext = invocation.turn_context.exec_context

        # Check if command is allowed
        allowed, reason = exec_context.can_execute_command(command)
        if not allowed:
            return ToolOutput(
                content=f"Command blocked by policy: {reason}",
                success=False,
            )

        # Check if approval needed
        if exec_context.requires_approval("run_terminal_cmd", is_write=False):
            # Request approval (implementation depends on environment)
            approval = await self._request_approval(invocation, command)
            if not approval:
                return ToolOutput(
                    content="Command execution denied by user",
                    success=False,
                )

        # Execute command
        # ... existing execution logic ...
```

**Migration Impact**: Medium - Add policy checks

**Benefits**:
- Prevent dangerous operations
- User control over agent actions
- Configurable security levels
- Audit trail for approvals

---

## Phase 10: Migration Checklist

### Priority 1: Core Architecture (Weeks 1-2)

- [ ] Create tool handler protocol (`tools/handler.py`)
- [ ] Implement tool registry (`tools/registry.py`)
- [ ] Create tool router (`tools/router.py`)
- [ ] Convert 2-3 simple tools to new architecture
- [ ] Update agent.py to use registry/router
- [ ] Add basic tests for new architecture

### Priority 2: Type Safety (Week 3)

- [ ] Add Pydantic to dependencies
- [ ] Create schema models for all tools
- [ ] Update tool implementations to use schemas
- [ ] Add validation tests
- [ ] Document schema patterns

### Priority 3: Parallel Execution (Week 4)

- [ ] Implement ToolCallRuntime with locking
- [ ] Add async support to agent.py
- [ ] Mark parallelizable tools
- [ ] Add parallel execution tests
- [ ] Measure performance improvements

### Priority 4: Output Management (Week 5)

- [ ] Create output formatter (`tools/output.py`)
- [ ] Implement head+tail truncation
- [ ] Update shell tool to use formatter
- [ ] Add truncation tests
- [ ] Document limits and behavior

### Priority 5: Turn Diff Tracking (Week 6)

- [ ] Create TurnDiffTracker class
- [ ] Update tools to record edits
- [ ] Add file locking mechanism
- [ ] Implement diff generation
- [ ] Add tracking tests

### Priority 6: Error Handling (Week 7)

- [ ] Define error types (`errors.py`)
- [ ] Update tools to use structured errors
- [ ] Add error recovery logic to agent
- [ ] Update tests for error scenarios
- [ ] Document error handling patterns

### Priority 7: Telemetry (Week 8)

- [ ] Enhance telemetry collector
- [ ] Add OTEL export format
- [ ] Integrate telemetry into registry
- [ ] Create telemetry dashboard
- [ ] Add telemetry tests

### Priority 8: Testing (Week 9)

- [ ] Create tool test harness
- [ ] Add tests for all tools
- [ ] Add parallel execution tests
- [ ] Add integration tests
- [ ] Achieve >80% test coverage

### Priority 9: MCP Integration (Week 10)

- [ ] Create MCP discovery module
- [ ] Implement schema sanitization
- [ ] Add MCP handler
- [ ] Test with existing MCP servers
- [ ] Document MCP tool registration

### Priority 10: Policies & Documentation (Week 11-12)

- [ ] Implement execution policies
- [ ] Add policy configuration
- [ ] Update documentation
- [ ] Create migration guide for users
- [ ] Final testing and polish

---

## Success Metrics

### Performance
- ✅ Parallel tool calls complete in 1/N time (N = parallelizable tools)
- ✅ Output truncation reduces context usage by 50%+
- ✅ Tool execution overhead < 50ms per call

### Reliability
- ✅ Test coverage > 80%
- ✅ Zero critical bugs in production
- ✅ Graceful degradation on errors
- ✅ Audit trail for all filesystem changes

### Maintainability
- ✅ Add new tool in < 30 minutes
- ✅ Clear error messages for all failures
- ✅ Self-documenting code with types
- ✅ Comprehensive API documentation

### User Experience
- ✅ Consistent tool behavior
- ✅ Predictable error handling
- ✅ Configurable safety policies
- ✅ Detailed telemetry for debugging

---

## Migration Anti-Patterns to Avoid

### ❌ Big Bang Rewrite
Don't try to migrate everything at once. Migrate incrementally:
1. Start with infrastructure (registry, router)
2. Convert 1-2 tools
3. Test thoroughly
4. Convert remaining tools
5. Add advanced features (parallel, telemetry)

### ❌ Breaking Existing Functionality
Maintain backward compatibility:
- Keep old tool interface working
- Add deprecation warnings
- Provide migration path
- Document breaking changes

### ❌ Over-Engineering
Don't add complexity without benefits:
- Start with simple patterns
- Add features as needed
- Measure before optimizing
- Keep it readable

### ❌ Ignoring Tests
Tests are critical for confidence:
- Write tests before refactoring
- Test edge cases
- Test error conditions
- Test parallel execution

---

## Conclusion

This migration will transform indubitably-code from a functional prototype into a production-ready, enterprise-grade coding assistant. The phased approach ensures:

1. **Incremental Progress**: Each phase delivers value
2. **Reduced Risk**: Small changes, thorough testing
3. **Learning Opportunity**: Understand patterns before applying
4. **Maintainability**: Clean architecture for future growth

The patterns from codex-rs have been battle-tested in production and represent years of engineering refinement. By adopting these patterns, indubitably-code will gain:

- **Robustness**: Handle edge cases gracefully
- **Performance**: Parallel execution, smart truncation
- **Maintainability**: Clean abstractions, easy to extend
- **Observability**: Comprehensive telemetry and logging
- **Safety**: Policies, validation, audit trails

**Estimated Timeline**: 12 weeks for full migration
**Team Size**: 1-2 developers
**Priority**: High - Foundation for production readiness

---

## Next Steps

1. **Review this migration guide** with team
2. **Set up project board** with checklist items
3. **Start Phase 1** (Core Architecture)
4. **Weekly check-ins** to track progress
5. **Adjust timeline** based on learnings

Good luck with the migration! 🚀
