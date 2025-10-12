import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_grep import grep_impl
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="grep",
        description="",
        input_schema={"type": "object"},
        fn=grep_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    (base / "src").mkdir(parents=True, exist_ok=True)
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object] | list[str]:
    output = asyncio.run(harness.invoke("grep", payload))
    return json.loads(output.content)


@pytest.fixture
def repo(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    harness, base = _harness(tmp_path)
    (base / "src" / "a.py").write_text("print('hello world')\n", encoding="utf-8")
    (base / "src" / "b.py").write_text("# TODO: refactor\n", encoding="utf-8")
    return harness, base


def test_grep_content_mode(repo: Tuple[ToolTestHarness, Path]):
    harness, base = repo
    output = _invoke(
        harness,
        {
            "pattern": "hello",
            "path": str(base / "src"),
        },
    )
    assert any("a.py" in line for line in output)


def test_grep_files_mode(repo: Tuple[ToolTestHarness, Path]):
    harness, base = repo
    output = _invoke(
        harness,
        {
            "pattern": "TODO",
            "path": str(base),
            "output_mode": "files_with_matches",
        },
    )
    assert str(base / "src" / "b.py") in output


def test_grep_count_mode(repo: Tuple[ToolTestHarness, Path]):
    harness, base = repo
    output = _invoke(
        harness,
        {
            "pattern": "print",
            "path": str(base / "src"),
            "output_mode": "count",
        },
    )
    assert output[str(base / "src" / "a.py")] == 1


def test_grep_missing_pattern(repo: Tuple[ToolTestHarness, Path]):
    harness, base = repo
    output = asyncio.run(harness.invoke("grep", {"path": str(base)}))
    assert output.success is False
    assert "pattern" in output.content
