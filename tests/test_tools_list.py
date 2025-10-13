import asyncio
import json
import os
import time

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_list import list_files_tool_def, list_files_impl
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    definition = list_files_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=list_files_impl,
    )


def _harness(tmp_path):
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def test_list_files_non_recursive(tmp_path, monkeypatch):
    harness, base = _harness(tmp_path)
    (base / "src").mkdir(parents=True)
    (base / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (base / "README.md").write_text("readme\n", encoding="utf-8")

    output = asyncio.run(harness.invoke("list_files", {"path": str(base), "recursive": False, "include_dirs": True}))
    result = json.loads(output.content)

    expected = {"src/", "README.md"}
    assert expected.issubset(set(result))


def test_list_files_with_glob_and_head_limit(tmp_path, monkeypatch):
    harness, base = _harness(tmp_path)
    (base / "pkg").mkdir(parents=True)
    for name in ["a.py", "b.txt", "c.py"]:
        (base / "pkg" / name).write_text("""pass""", encoding="utf-8")

    output = asyncio.run(harness.invoke("list_files", {
        "path": str(base / "pkg"),
        "glob": "*.py",
        "include_dirs": False,
        "head_limit": 1,
        "sort_by": "name",
    }))
    result = json.loads(output.content)

    assert result == ["a.py"]
