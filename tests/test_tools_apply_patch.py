import json

from tools_apply_patch import apply_patch_impl


def test_apply_patch_add_update_delete(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    add_patch = """*** Add File: notes.txt
@@
Hello
World
"""
    add_result = json.loads(apply_patch_impl({"file_path": "notes.txt", "patch": add_patch}))
    assert add_result["ok"] is True
    assert (base / "notes.txt").read_text(encoding="utf-8") == "Hello\nWorld\n"

    update_patch = """*** Update File: notes.txt
- Hello
+ Goodbye
"""
    update_result = json.loads(apply_patch_impl({"file_path": "notes.txt", "patch": update_patch}))
    assert update_result["ok"] is True
    assert (base / "notes.txt").read_text(encoding="utf-8") == "Goodbye\nWorld\n"

    delete_patch = """*** Delete File: notes.txt
"""
    delete_result = json.loads(apply_patch_impl({"file_path": "notes.txt", "patch": delete_patch}))
    assert delete_result["ok"] is True
    assert not (base / "notes.txt").exists()
