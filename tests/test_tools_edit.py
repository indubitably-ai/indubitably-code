import asyncio
import json
from pathlib import Path

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_edit import edit_file_impl, edit_file_tool_def
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    definition = edit_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=edit_file_impl,
    )


def _harness(tmp_path: Path) -> tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def test_edit_file_full_flow(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("hello world", encoding="utf-8")
    out = asyncio.run(harness.invoke("edit_file", {"path": str(path), "old_str": "world", "new_str": "python"}))
    result = json.loads(out.content)
    assert result["ok"] is True
    assert path.read_text(encoding="utf-8") == "hello python"


def test_edit_file_dry_run_reports(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("foo foo", encoding="utf-8")
    out = asyncio.run(harness.invoke("edit_file", {"path": str(path), "old_str": "foo", "new_str": "bar", "dry_run": True}))
    result = json.loads(out.content)
    assert result["dry_run"] is True
    assert result["replacements"] == 2
    assert path.read_text(encoding="utf-8") == "foo foo"


def test_edit_file_missing_old_returns_error(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("hello", encoding="utf-8")
    out = asyncio.run(harness.invoke("edit_file", {"path": str(path), "old_str": "absent", "new_str": "value"}))
    assert out.success is False
    assert "absent" in out.content or "not found" in out.content.lower()


def test_edit_file_create_new(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "new.txt"
    out = asyncio.run(harness.invoke("edit_file", {"path": str(path), "old_str": "", "new_str": "content"}))
    result = json.loads(out.content)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "content"
    assert result["action"] == "create"


