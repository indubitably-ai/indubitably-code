import json

from tools_list import list_files_impl


def test_list_files_non_recursive(tmp_path, monkeypatch):
    base = tmp_path / "proj"
    (base / "src").mkdir(parents=True)
    (base / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (base / "README.md").write_text("readme\n", encoding="utf-8")

    monkeypatch.chdir(base)

    result = json.loads(list_files_impl({"recursive": False, "include_dirs": True}))

    assert set(result) == {"README.md", "src/"}


def test_list_files_with_glob_and_head_limit(tmp_path, monkeypatch):
    base = tmp_path / "workspace"
    (base / "pkg").mkdir(parents=True)
    for name in ["a.py", "b.txt", "c.py"]:
        (base / "pkg" / name).write_text("""pass""", encoding="utf-8")

    monkeypatch.chdir(base)

    result = json.loads(list_files_impl({
        "path": "pkg",
        "glob": "*.py",
        "include_dirs": False,
        "head_limit": 1,
        "sort_by": "name",
    }))

    assert result == ["a.py"]
