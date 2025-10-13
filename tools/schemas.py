"""Pydantic schemas for validated tool inputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Type

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class ToolSchema(BaseModel):
    """Base class for all tool schemas with strict validation."""

    model_config = {
        "extra": "forbid",
        "validate_assignment": True,
    }

    def dump(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ReadFileInput(ToolSchema):
    path: str = Field(..., min_length=1, description="Relative or absolute path to a file")
    encoding: Optional[str] = Field("utf-8", description="Text encoding to use")
    errors: Optional[str] = Field("replace", description="Decoding error policy")
    byte_offset: Optional[int] = Field(None, ge=0, description="Start byte offset")
    byte_limit: Optional[int] = Field(None, gt=0, description="Max bytes to read")
    offset: Optional[int] = Field(None, ge=1, description="1-based line offset")
    limit: Optional[int] = Field(None, gt=0, description="Number of lines to read")
    tail_lines: Optional[int] = Field(None, gt=0, description="Return last N lines")


class RunTerminalCmdInput(ToolSchema):
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
    def validate_command(cls, value: str) -> str:
        dangerous = ("rm -rf /", "dd if=", ":(){ :|:& };:")
        if any(pattern in value for pattern in dangerous):
            raise ValueError("command contains dangerous patterns")
        return value

    @field_validator("stdin")
    @classmethod
    def validate_stdin(cls, value: Optional[str], info) -> Optional[str]:
        if value is not None and info.data.get("is_background"):
            raise ValueError("stdin not supported with background jobs")
        return value


class EditFileInput(ToolSchema):
    path: str = Field(..., min_length=1)
    old_str: str = Field(...)
    new_str: str = Field(...)
    dry_run: bool = False

    @field_validator("new_str")
    @classmethod
    def ensure_difference(cls, value: str, info) -> str:
        if "old_str" in info.data and info.data["old_str"] == value and info.data["old_str"] != "":
            raise ValueError("new_str must differ from old_str")
        return value


class CreateFileInput(ToolSchema):
    path: str = Field(..., min_length=1)
    content: str = ""
    if_exists: str = Field("error")
    create_parents: bool = True
    encoding: str = Field("utf-8")
    dry_run: bool = False

    @field_validator("if_exists")
    @classmethod
    def validate_policy(cls, value: str) -> str:
        policy = value.lower()
        if policy not in {"error", "overwrite", "skip"}:
            raise ValueError("if_exists must be one of error, overwrite, skip")
        return policy


class DeleteFileInput(ToolSchema):
    path: str = Field(..., min_length=1)


class RenameFileInput(ToolSchema):
    source_path: str = Field(..., min_length=1)
    dest_path: str = Field(..., min_length=1)
    overwrite: bool = False
    create_dest_parent: bool = True
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_paths(self) -> "RenameFileInput":
        if Path(self.source_path).resolve() == Path(self.dest_path).resolve():
            raise ValueError("source and destination paths are identical")
        return self


class GrepInput(ToolSchema):
    pattern: str = Field(..., min_length=1)
    path: str = Field(".")
    include: Optional[str] = None
    context_lines: int = Field(0, ge=0, le=10)
    case_insensitive: bool = False
    max_results: int = Field(100, ge=1, le=1000)
    output_mode: str = Field("content")
    before: int = Field(0, ge=0)
    after: int = Field(0, ge=0)
    around: int = Field(0, ge=0)
    multiline: bool = False
    head_limit: Optional[int] = Field(None, ge=1)


LINE_EDIT_MODES = {"insert_before", "insert_after", "replace", "delete"}


class LineEditInput(ToolSchema):
    path: str = Field(..., min_length=1)
    mode: str = Field(...)
    line: Optional[int] = Field(None, ge=1)
    anchor: Optional[str] = None
    occurrence: int = Field(1, ge=1)
    line_count: int = Field(1, ge=1)
    text: Optional[str] = None
    dry_run: bool = False

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        mode = value.lower()
        if mode not in LINE_EDIT_MODES:
            raise ValueError(f"mode must be one of {sorted(LINE_EDIT_MODES)}")
        return mode

    @model_validator(mode="after")
    def validate_position(self) -> "LineEditInput":
        if (self.line is None) == (self.anchor is None):
            raise ValueError("specify either line or anchor")

        if self.mode in {"insert_before", "insert_after", "replace"}:
            if self.text is None or self.text == "":
                raise ValueError("text is required for insert/replace modes")
        if self.mode == "delete" and self.text not in (None, ""):
            raise ValueError("text must be omitted for delete mode")
        return self


class ApplyPatchInput(ToolSchema):
    file_path: str = Field(..., min_length=1)
    patch: str = Field(..., min_length=1)
    dry_run: bool = False


TEMPLATE_MODES = {"insert_before", "insert_after", "replace_block"}


class TemplateBlockInput(ToolSchema):
    path: str = Field(..., min_length=1)
    mode: Literal["insert_before", "insert_after", "replace_block"]
    anchor: str = Field(..., min_length=1)
    occurrence: int = Field(1, ge=1)
    template: str = Field(..., min_length=1)
    expected_block: Optional[str] = None
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_expected_block(self) -> "TemplateBlockInput":
        if self.mode != "replace_block" and self.expected_block is not None:
            raise ValueError("expected_block is only valid for replace_block mode")
        return self


TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class TodoItemInput(ToolSchema):
    id: str = Field(..., min_length=1)
    content: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in TODO_STATUSES:
            raise ValueError(f"status must be one of {sorted(TODO_STATUSES)}")
        return value


class TodoWriteInput(ToolSchema):
    merge: bool = False
    todos: List[TodoItemInput] = Field(default_factory=list)


# --- New schemas for additional tools (Phase 1) ---

class ListFilesInput(ToolSchema):
    path: Optional[str] = None
    recursive: bool = True
    max_depth: Optional[int] = Field(None, ge=1)
    glob: Optional[str] = None
    ignore_globs: List[str] = Field(default_factory=list)
    include_files: bool = True
    include_dirs: bool = True
    sort_by: Literal["name", "mtime", "size"] = "name"
    sort_order: Literal["asc", "desc"] = "asc"
    head_limit: Optional[int] = Field(None, ge=1)


class GlobFileSearchInput(ToolSchema):
    target_directory: Optional[str] = None
    glob_pattern: str = Field(..., min_length=1)
    head_limit: Optional[int] = Field(None, ge=1)


class CodebaseSearchInput(ToolSchema):
    query: str = Field(..., min_length=1)
    target_directories: List[str] = Field(default_factory=list)
    glob_pattern: Optional[str] = None
    max_results: int = Field(10, ge=1)
    snippet_lines: int = Field(2, ge=0)


class WebSearchInput(ToolSchema):
    search_term: str = Field(..., min_length=1)
    explanation: Optional[str] = None
    max_results: int = Field(10, ge=1)


_TOOL_SCHEMAS: Dict[str, Type[ToolSchema]] = {
    "read_file": ReadFileInput,
    "run_terminal_cmd": RunTerminalCmdInput,
    "grep": GrepInput,
    "edit_file": EditFileInput,
    "create_file": CreateFileInput,
    "delete_file": DeleteFileInput,
    "rename_file": RenameFileInput,
    "line_edit": LineEditInput,
    "apply_patch": ApplyPatchInput,
    "template_block": TemplateBlockInput,
    "todo_write": TodoWriteInput,
    # Newly registered schemas
    "list_files": ListFilesInput,
    "glob_file_search": GlobFileSearchInput,
    "codebase_search": CodebaseSearchInput,
    "web_search": WebSearchInput,
}


def parse_tool_input(tool_name: str, raw_input: Mapping[str, Any]) -> ToolSchema | Dict[str, Any]:
    """Parse and validate raw input into a Pydantic model instance.

    Returns a ``ToolSchema`` instance when a schema is registered; otherwise,
    a fallback model with raw fields is not created and the raw mapping is
    returned wrapped in a lightweight shim via ``AnonymousSchema`` below.
    """
    schema = _TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        # Pass through unknown tools unchanged (legacy compatibility for tests)
        return dict(raw_input)
    try:
        model = schema(**raw_input)
    except ValidationError as exc:  # pragma: no cover - error formatting
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages))
    return model


def validate_tool_input(tool_name: str, raw_input: Mapping[str, Any]) -> Dict[str, Any]:
    """Legacy helper returning dicts; delegates to ``parse_tool_input``."""
    model = parse_tool_input(tool_name, raw_input)
    if isinstance(model, dict):
        return dict(model)
    return model.dump()


__all__ = [
    "ToolSchema",
    "ReadFileInput",
    "RunTerminalCmdInput",
    "GrepInput",
    "EditFileInput",
    "CreateFileInput",
    "DeleteFileInput",
    "RenameFileInput",
    "LineEditInput",
    "ApplyPatchInput",
    "TemplateBlockInput",
    "TodoItemInput",
    "TodoWriteInput",
    "ListFilesInput",
    "GlobFileSearchInput",
    "CodebaseSearchInput",
    "WebSearchInput",
    "TODO_STATUSES",
    "TEMPLATE_MODES",
    "LINE_EDIT_MODES",
    "parse_tool_input",
    "validate_tool_input",
]
