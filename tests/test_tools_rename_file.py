import asyncio
import json
from pathlib import Path

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools.schemas import RenameFileInput
from tools_rename_file import rename_file_impl, rename_file_tool_def
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    definition = rename_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=rename_file_impl,
    )


def _harness(tmp_path: Path) -> tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _harness_for_base(base: Path) -> ToolTestHarness:
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context)


def _invoke(harness: ToolTestHarness, payload: dict) -> dict:
    out = asyncio.run(harness.invoke("rename_file", payload))
    return json.loads(out.content)


def test_basic_rename(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    harness = _harness_for_base(base)

    src = base / "one.txt"
    src.write_text("data", encoding="utf-8")

    result = _invoke(harness, {"source_path": "one.txt", "dest_path": "two.txt"})
    assert result["ok"] is True
    assert result["action"] == "rename"
    assert (base / "two.txt").read_text(encoding="utf-8") == "data"


def test_rename_creates_parent(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    harness = _harness_for_base(base)

    src = base / "src.txt"
    src.write_text("data", encoding="utf-8")

    dest = base / "dir" / "sub" / "target.txt"
    result = _invoke(harness, {"source_path": "src.txt", "dest_path": str(dest.relative_to(base))})
    assert result["ok"] is True
    assert (base / dest).read_text(encoding="utf-8") == "data"


def test_rename_without_overwrite(tmp_path, monkeypatch):
    harness, base = _harness(tmp_path)
    src = base / "one.txt"
    dst = base / "two.txt"
    src.write_text("src", encoding="utf-8")
    dst.write_text("dst", encoding="utf-8")

    output = asyncio.run(harness.invoke("rename_file", {"source_path": str(src), "dest_path": str(dst), "overwrite": False}))
    assert output.success is False
    assert output.metadata and output.metadata.get("error_type") == "exists"


def test_overwrite_flag(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    harness = _harness_for_base(base)

    src = base / "one.txt"
    src.write_text("src", encoding="utf-8")
    (base / "two.txt").write_text("dst", encoding="utf-8")

    result = _invoke(harness, {"source_path": "one.txt", "dest_path": "two.txt", "overwrite": True})
    assert result["ok"] is True
    assert (base / "two.txt").read_text(encoding="utf-8") == "src"


def test_rename_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    harness = _harness_for_base(base)

    src = base / "one.txt"
    src.write_text("data", encoding="utf-8")
    dest = base / "two.txt"

    result = _invoke(harness, {"source_path": "one.txt", "dest_path": "two.txt", "dry_run": True})
    assert result["dry_run"] is True
    assert src.exists() and not dest.exists()


def test_missing_parent_without_create(tmp_path, monkeypatch):
    harness, base = _harness(tmp_path)
    (base / "file.txt").write_text("data", encoding="utf-8")

    output = asyncio.run(harness.invoke("rename_file", {"source_path": str(base / "file.txt"), "dest_path": str(base / "missing/dir/out.txt"), "create_dest_parent": False}))
    assert output.success is False
    assert output.metadata and output.metadata.get("error_type") == "not_found"


def test_reject_identical_paths(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "same.txt").write_text("data", encoding="utf-8")

    with pytest.raises(ValueError):
        rename_file_impl(RenameFileInput(source_path="same.txt", dest_path="same.txt"))


def test_error_on_directory_source(tmp_path, monkeypatch):
    harness, base = _harness(tmp_path)
    (base / "dir_src").mkdir()

    output = asyncio.run(harness.invoke("rename_file", {"source_path": str(base / "dir_src"), "dest_path": str(base / "x.txt")}))
    assert output.success is False
    assert output.metadata and output.metadata.get("error_type") == "is_directory"


