import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_read import read_file_impl
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="read_file",
        description="",
        input_schema={"type": "object"},
        fn=read_file_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir(exist_ok=True)
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> asyncio.Future:
    return harness.invoke("read_file", payload)


@pytest.fixture
def sample_file(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    harness, base = _harness(tmp_path)
    path = base / "sample.txt"
    path.write_text("one\nsecond\nthird\nfourth\n", encoding="utf-8")
    return harness, path


def test_read_file_full(sample_file: Tuple[ToolTestHarness, Path]):
    harness, path = sample_file
    output = asyncio.run(_invoke(harness, {"path": str(path)}))
    assert output.success is True
    data = json.loads(output.content)
    assert data["content"].startswith("one")
    assert "fourth" in data["content"]


def test_read_file_tail_lines(sample_file: Tuple[ToolTestHarness, Path]):
    harness, path = sample_file
    output = asyncio.run(_invoke(harness, {"path": str(path), "tail_lines": 2}))
    assert output.success is True
    data = json.loads(output.content)
    assert data["content"].splitlines() == ["third", "fourth"]


def test_read_file_line_range(sample_file: Tuple[ToolTestHarness, Path]):
    harness, path = sample_file
    output = asyncio.run(_invoke(harness, {"path": str(path), "offset": 2, "limit": 1}))
    assert json.loads(output.content)["content"] == "second"


def test_read_file_missing_path_returns_error(tmp_path: Path):
    harness, _ = _harness(tmp_path)
    output = asyncio.run(_invoke(harness, {}))
    assert output.success is False
    assert "path" in output.content


def test_read_file_directory_errors(tmp_path: Path):
    harness, base = _harness(tmp_path)
    output = asyncio.run(_invoke(harness, {"path": str(base)}))
    assert output.success is False
    assert "directory" in output.content.lower()


def test_read_file_byte_range(sample_file: Tuple[ToolTestHarness, Path]):
    harness, path = sample_file
    output = asyncio.run(
        _invoke(
            harness,
            {"path": str(path), "byte_offset": 4, "byte_limit": 2},
        )
    )
    assert json.loads(output.content)["content"] == "se"
