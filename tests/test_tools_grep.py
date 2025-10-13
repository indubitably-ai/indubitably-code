import json
from tools.handler import ToolOutput
from tools.schemas import GrepInput
from tools_grep import grep_impl


def test_grep_files_with_matches(tmp_path):
    target = tmp_path / "pkg"
    target.mkdir()
    file_path = target / "main.py"
    file_path.write_text("print('needle')\n", encoding="utf-8")

    result: ToolOutput = grep_impl(GrepInput(pattern="needle", path=str(tmp_path), output_mode="files_with_matches"))
    assert result.success is True
    data = json.loads(result.content)
    assert str(file_path) in data["files"]
