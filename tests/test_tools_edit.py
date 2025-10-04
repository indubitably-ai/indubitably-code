import json

import pytest

from tools_edit import edit_file_impl


def test_edit_file_create_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    result = json.loads(
        edit_file_impl({
            "path": "example.txt",
            "old_str": "",
            "new_str": "hello\n",
            "dry_run": True,
        })
    )

    assert result == {"ok": True, "action": "create", "path": "example.txt", "dry_run": True}
    assert not (base / "example.txt").exists()


def test_edit_file_replace_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "sample.txt"
    target.write_text("value=1\n", encoding="utf-8")

    result = json.loads(
        edit_file_impl({
            "path": "sample.txt",
            "old_str": "value=1",
            "new_str": "value=2",
            "dry_run": True,
        })
    )

    assert result == {"ok": True, "action": "replace", "path": "sample.txt", "dry_run": True, "replacements": 1}
    assert target.read_text(encoding="utf-8") == "value=1\n"


def test_edit_file_replace_executes(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "sample.txt"
    target.write_text("value=1\n", encoding="utf-8")

    result = json.loads(edit_file_impl({
        "path": "sample.txt",
        "old_str": "value=1",
        "new_str": "value=2",
    }))

    assert result == {"ok": True, "action": "replace", "path": "sample.txt", "replacements": 1}
    assert target.read_text(encoding="utf-8") == "value=2\n"


def test_edit_file_large_file_warning(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    lines = "\n".join(f"line{i}" for i in range(2100)) + "\n"
    (base / "large.txt").write_text(lines, encoding="utf-8")

    result = json.loads(edit_file_impl({
        "path": "large.txt",
        "old_str": "line0",
        "new_str": "line_zero",
        "dry_run": True,
    }))

    assert result["dry_run"] is True
    assert "warning" in result
    assert "file has" in result["warning"]


def test_edit_file_multiple_matches_warning(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "multi.txt").write_text("foo foo foo\n", encoding="utf-8")

    result = json.loads(edit_file_impl({
        "path": "multi.txt",
        "old_str": "foo",
        "new_str": "bar",
        "dry_run": True,
    }))

    assert result["replacements"] == 3
    assert "warning" in result
    assert "multiple matches" in result["warning"]


def test_edit_file_missing_old_raises(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "sample.txt"
    target.write_text("value=1\n", encoding="utf-8")

    with pytest.raises(ValueError):
        edit_file_impl({
            "path": "sample.txt",
            "old_str": "other",
            "new_str": "value=2",
        })


