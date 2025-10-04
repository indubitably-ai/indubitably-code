import json

import pytest

from tools_line_edit import line_edit_impl


def _call(payload):
    return json.loads(line_edit_impl(payload))


def test_insert_before_first_line(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "sample.txt"
    target.write_text("a\nb\n", encoding="utf-8")

    result = _call(
        {
            "path": "sample.txt",
            "mode": "insert_before",
            "line": 1,
            "text": "intro\n",
        }
    )

    assert result["ok"] is True
    assert result["action"] == "insert_before"
    assert result["path"] == "sample.txt"
    assert result["line"] == 1
    assert result["lines_changed"] == 1
    assert result["offset_start"] == 0
    assert result["offset_end"] == 0
    assert "total_lines" in result
    assert target.read_text(encoding="utf-8") == "intro\na\nb\n"


def test_insert_after_anchor_occurrence(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "notes.txt"
    target.write_text("alpha\nbeta\nalpha\n", encoding="utf-8")

    result = _call(
        {
            "path": "notes.txt",
            "mode": "insert_after",
            "anchor": "alpha",
            "occurrence": 2,
            "text": "omega\n",
        }
    )

    assert result["anchor"] == "alpha"
    assert result["line"] == 4
    assert result["offset_end"] == result["offset_start"]
    assert "total_lines" in result
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\nalpha\nomega\n"


def test_replace_multiple_lines(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "config.txt"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")

    result = _call(
        {
            "path": "config.txt",
            "mode": "replace",
            "line": 2,
            "line_count": 2,
            "text": "new2\nnew3\n",
        }
    )

    assert result["lines_changed"] == 2
    assert result["offset_end"] > result["offset_start"]
    assert target.read_text(encoding="utf-8") == "line1\nnew2\nnew3\n"


def test_delete_with_anchor(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "app.log"
    target.write_text("keep\nremove\nrest\n", encoding="utf-8")

    result = _call(
        {
            "path": "app.log",
            "mode": "delete",
            "anchor": "remove",
        }
    )

    assert result["ok"] is True
    assert result["action"] == "delete"
    assert result["anchor"] == "remove"
    assert result["line"] == 2
    assert result["lines_changed"] == 1
    assert result["path"] == "app.log"
    assert result["offset_end"] - result["offset_start"] == len("remove\n")
    assert "total_lines" in result
    assert target.read_text(encoding="utf-8") == "keep\nrest\n"


def test_invalid_text_for_insert(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "t.txt").write_text("only\n", encoding="utf-8")

    with pytest.raises(ValueError):
        line_edit_impl({"path": "t.txt", "mode": "insert_before", "line": 1, "text": ""})


def test_line_edit_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "file.txt"
    target.write_text("one\n", encoding="utf-8")

    result = json.loads(line_edit_impl({
        "path": "file.txt",
        "mode": "insert_after",
        "line": 1,
        "text": "two\n",
        "dry_run": True,
    }))

    assert result["dry_run"] is True
    assert "offset_start" in result and "offset_end" in result
    assert target.read_text(encoding="utf-8") == "one\n"


def test_line_edit_large_file_warning(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    big_lines = "\n".join(f"line{i}" for i in range(2100)) + "\n"
    (base / "big.txt").write_text(big_lines, encoding="utf-8")

    result = json.loads(line_edit_impl({
        "path": "big.txt",
        "mode": "insert_after",
        "line": 1,
        "text": "inserted\n",
        "dry_run": True,
    }))

    assert result["dry_run"] is True
    assert "warning" in result and "file has" in result["warning"]
    assert "offset_start" in result and "offset_end" in result


def test_anchor_not_found(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "f.txt").write_text("one\ntwo\n", encoding="utf-8")

    with pytest.raises(ValueError):
        line_edit_impl({"path": "f.txt", "mode": "delete", "anchor": "missing"})
