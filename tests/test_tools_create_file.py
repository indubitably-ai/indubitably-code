import json
import pytest

from tools_create_file import create_file_impl


def _call(payload):
    return json.loads(create_file_impl(payload))


def test_create_new_file(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    result = _call({"path": "data.txt", "content": "hello"})
    assert result["action"] == "create"
    assert result["path"] == "data.txt"
    assert (base / "data.txt").read_text(encoding="utf-8") == "hello"


def test_skip_existing(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "file.txt"
    target.write_text("existing", encoding="utf-8")

    result = _call({"path": "file.txt", "if_exists": "skip", "content": "new"})
    assert result == {"ok": True, "action": "skip", "path": "file.txt"}
    assert target.read_text(encoding="utf-8") == "existing"


def test_create_file_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    result = _call({"path": "data.txt", "content": "hello", "dry_run": True})
    assert result["dry_run"] is True
    assert not (base / "data.txt").exists()


def test_overwrite_existing(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    target = base / "file.txt"
    target.write_text("old", encoding="utf-8")

    result = _call({"path": "file.txt", "if_exists": "overwrite", "content": "new"})
    assert result["action"] == "overwrite"
    assert target.read_text(encoding="utf-8") == "new"


def test_missing_parent_without_create(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    with pytest.raises(FileNotFoundError):
        create_file_impl({
            "path": "missing/dir/file.txt",
            "content": "data",
            "create_parents": False,
        })


def test_error_on_existing_when_policy_error(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "file.txt").write_text("data", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_file_impl({"path": "file.txt"})


def test_error_on_directory_path(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "dir").mkdir()

    with pytest.raises(IsADirectoryError):
        create_file_impl({"path": "dir"})


