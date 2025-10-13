import json
import os
import time

from tools.handler import ToolOutput
from tools.schemas import GlobFileSearchInput
from tools_glob_file_search import glob_file_search_impl


def test_glob_file_search_returns_relative_paths(tmp_path, monkeypatch):
    base = tmp_path / "workspace"
    src = base / "src"
    src.mkdir(parents=True)
    file_a = src / "app.py"
    file_b = src / "util.py"
    file_a.write_text("print('a')\n", encoding="utf-8")
    time.sleep(0.01)  # ensure mtime ordering differences
    file_b.write_text("print('b')\n", encoding="utf-8")

    monkeypatch.chdir(base)

    result: ToolOutput = glob_file_search_impl(GlobFileSearchInput(glob_pattern="*.py", head_limit=1))
    assert result.success is True
    paths = json.loads(result.content)
    assert paths == ["src/util.py"]
