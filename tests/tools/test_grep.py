import json
from pathlib import Path

import pytest

from tools_grep import grep_impl


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('hello world')\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# TODO: refactor\n", encoding="utf-8")
    return tmp_path


def test_grep_content_mode(repo: Path):
    output = json.loads(
        grep_impl({
            "pattern": "hello",
            "path": str(repo / "src"),
        })
    )
    assert any("a.py" in line for line in output)


def test_grep_files_mode(repo: Path):
    output = json.loads(
        grep_impl({
            "pattern": "TODO",
            "path": str(repo),
            "output_mode": "files_with_matches",
        })
    )
    assert str(repo / "src" / "b.py") in output


def test_grep_count_mode(repo: Path):
    output = json.loads(
        grep_impl({
            "pattern": "print",
            "path": str(repo / "src"),
            "output_mode": "count",
        })
    )
    assert output[str(repo / "src" / "a.py")] == 1


def test_grep_missing_pattern():
    with pytest.raises(ValueError):
        grep_impl({})
