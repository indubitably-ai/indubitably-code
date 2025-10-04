import json
import os
import pytest

from tools_rename_file import rename_file_impl


def _invoke(payload):
    return json.loads(rename_file_impl(payload))


def test_basic_rename(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    src = base / "one.txt"
    src.write_text("data", encoding="utf-8")

    result = _invoke({"source_path": "one.txt", "dest_path": "two.txt"})
    assert result == {
        "ok": True,
        "action": "rename",
        "source": "one.txt",
        "destination": "two.txt",
        "overwritten": False,
    }
    assert not src.exists()
    assert (base / "two.txt").read_text(encoding="utf-8") == "data"


def test_rename_creates_parent(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    src = base / "src.txt"
    src.write_text("data", encoding="utf-8")

    dest = base / "dir" / "sub" / "target.txt"
    result = _invoke({
        "source_path": "src.txt",
        "dest_path": str(dest.relative_to(base)),
    })
    assert result["destination"] == "dir/sub/target.txt"
    assert dest.read_text(encoding="utf-8") == "data"


def test_rename_without_overwrite(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    src = base / "one.txt"
    src.write_text("src", encoding="utf-8")
    (base / "two.txt").write_text("dst", encoding="utf-8")

    with pytest.raises(FileExistsError):
        rename_file_impl({"source_path": "one.txt", "dest_path": "two.txt"})


def test_overwrite_flag(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    src = base / "one.txt"
    src.write_text("src", encoding="utf-8")
    (base / "two.txt").write_text("dst", encoding="utf-8")

    result = _invoke({
        "source_path": "one.txt",
        "dest_path": "two.txt",
        "overwrite": True,
    })
    assert result["overwritten"] is True
    assert (base / "two.txt").read_text(encoding="utf-8") == "src"


def test_rename_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    src = base / "one.txt"
    src.write_text("data", encoding="utf-8")
    dest = base / "two.txt"

    result = _invoke({"source_path": "one.txt", "dest_path": "two.txt", "dry_run": True})
    assert result["dry_run"] is True
    assert src.exists()
    assert not dest.exists()


def test_missing_parent_without_create(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "file.txt").write_text("data", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        rename_file_impl({
            "source_path": "file.txt",
            "dest_path": "missing/dir/out.txt",
            "create_dest_parent": False,
        })


def test_reject_identical_paths(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "same.txt").write_text("data", encoding="utf-8")

    with pytest.raises(ValueError):
        rename_file_impl({"source_path": "same.txt", "dest_path": "same.txt"})


def test_error_on_directory_source(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "dir_src").mkdir()

    with pytest.raises(IsADirectoryError):
        rename_file_impl({"source_path": "dir_src", "dest_path": "file.txt"})


