import json
import pytest

from tools_template_block import template_block_impl


def _call(payload):
    return json.loads(template_block_impl(payload))


def test_insert_before_anchor(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "sample.txt"
    target.write_text("header\nbody\n", encoding="utf-8")

    dry_preview = _call({
        "path": "sample.txt",
        "mode": "insert_before",
        "anchor": "body\n",
        "template": "alpha\nbeta\n",
        "dry_run": True,
    })
    assert dry_preview["ok"] is True
    assert dry_preview["dry_run"] is True
    assert dry_preview["target_line"] == 2
    assert dry_preview["template_line_count"] == 2
    assert "total_lines" in dry_preview
    assert "warning" not in dry_preview

    result = _call({
        "path": "sample.txt",
        "mode": "insert_before",
        "anchor": "body\n",
        "template": "alpha\nbeta\n",
    })
    assert result["ok"] is True
    expected_offset = len("header\n")
    assert result["offset_start"] == expected_offset
    assert result["offset_end"] == expected_offset
    assert target.read_text(encoding="utf-8") == "header\nalpha\nbeta\nbody\n"


def test_insert_after_occurrence(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "data.txt"
    target.write_text("item\nitem\n", encoding="utf-8")

    result = _call({
        "path": "data.txt",
        "mode": "insert_after",
        "anchor": "item\n",
        "occurrence": 2,
        "template": "tail\n",
    })
    expected_offset = len("item\nitem\n")
    assert result["offset_start"] == expected_offset
    assert result["offset_end"] == expected_offset
    assert target.read_text(encoding="utf-8") == "item\nitem\ntail\n"


def test_replace_block(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "config.ini"
    target.write_text("[section]\nkey=value\n", encoding="utf-8")

    result = _call({
        "path": "config.ini",
        "mode": "replace_block",
        "anchor": "key=value\n",
        "expected_block": "key=value\n",
        "template": "key=new\n",
    })
    assert result["ok"] is True
    assert "total_lines" in result
    assert result["offset_end"] > result["offset_start"]
    assert target.read_text(encoding="utf-8") == "[section]\nkey=new\n"


def test_replace_mismatch_returns_error(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "config.ini"
    target.write_text("[section]\nkey=value\n", encoding="utf-8")

    result = _call({
        "path": "config.ini",
        "mode": "replace_block",
        "anchor": "key=value\n",
        "expected_block": "key=other\n",
        "template": "key=new\n",
    })
    assert result["ok"] is False
    assert result["error"] == "existing block does not match expected_block"


def test_anchor_not_found(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "file.txt").write_text("content\n", encoding="utf-8")

    result = json.loads(template_block_impl({
        "path": "file.txt",
        "mode": "insert_after",
        "anchor": "missing\n",
        "template": "new\n",
    }))
    assert result["ok"] is False
    assert "not found" in result["error"]
    assert result.get("total_lines") == 1




def test_template_block_large_file_warning(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    content = "\n".join(f"line{i}" for i in range(2050)) + "\n"
    (base / "large.txt").write_text(content, encoding="utf-8")

    preview = _call({
        "path": "large.txt",
        "mode": "insert_after",
        "anchor": "line0",
        "template": "added\n",
        "dry_run": True,
    })
    assert "warning" in preview and "file has" in preview["warning"]
    assert preview["total_lines"] >= 2050

    result = _call({
        "path": "large.txt",
        "mode": "insert_after",
        "anchor": "line0",
        "template": "added\n",
    })
    assert "warning" in result
    assert result["offset_end"] == result["offset_start"]
    assert "added\n" in (base / "large.txt").read_text(encoding="utf-8")
