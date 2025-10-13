import json
from difflib import unified_diff

from tools_apply_patch import apply_patch_impl
from tools.schemas import ApplyPatchInput


def test_apply_patch_add_update_delete(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    add_patch = """*** Add File: notes.txt
@@
Hello
World
"""
    add_result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="notes.txt", patch=add_patch)).content)
    assert add_result["ok"] is True
    assert (base / "notes.txt").read_text(encoding="utf-8") == "Hello\nWorld\n"

    update_patch = """*** Update File: notes.txt
- Hello
+ Goodbye
"""
    update_result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="notes.txt", patch=update_patch)).content)
    assert update_result["ok"] is True
    assert (base / "notes.txt").read_text(encoding="utf-8") == "Goodbye\nWorld\n"

    delete_patch = """*** Delete File: notes.txt
"""
    delete_result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="notes.txt", patch=delete_patch)).content)
    assert delete_result["ok"] is True
    assert not (base / "notes.txt").exists()


def test_apply_patch_handles_unified_diff_multi_hunks(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    original = "a\nb\nc\nd\ne\n"
    updated = "a\nalpha\nb\nc\nd\necho\n"
    (base / "sample.txt").write_text(original, encoding="utf-8")

    diff_body = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="sample.txt",
            tofile="sample.txt",
            lineterm="\n",
        )
    )
    patch = f"*** Update File: sample.txt\n{diff_body}"

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="sample.txt", patch=patch)).content)
    assert result == {"ok": True, "action": "Update", "path": "sample.txt"}
    assert (base / "sample.txt").read_text(encoding="utf-8") == updated


def test_apply_patch_supports_insert_only_hunk(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    original = "header\nbody\n"
    updated = "header\nbody\nextra\nmore\n"
    (base / "doc.txt").write_text(original, encoding="utf-8")

    diff_body = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="doc.txt",
            tofile="doc.txt",
            lineterm="\n",
        )
    )
    patch = f"*** Update File: doc.txt\n{diff_body}"

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="doc.txt", patch=patch)).content)
    assert result == {"ok": True, "action": "Update", "path": "doc.txt"}
    assert (base / "doc.txt").read_text(encoding="utf-8") == updated


def test_apply_patch_unified_delete(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "old.txt").write_text("line1\nline2\n", encoding="utf-8")

    delete_patch = """*** Delete File: old.txt
--- old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2
"""

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="old.txt", patch=delete_patch)).content)
    assert result["ok"] is True
    assert not (base / "old.txt").exists()


def test_apply_patch_dry_run(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "file.txt").write_text("foo\n", encoding="utf-8")

    patch = """*** Update File: file.txt
- foo
+ bar
"""

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="file.txt", patch=patch, dry_run=True)).content)
    assert result == {
        "ok": True,
        "action": "Update",
        "path": "file.txt",
        "dry_run": True,
    }
    assert (base / "file.txt").read_text(encoding="utf-8") == "foo\n"


def test_apply_patch_conflict_detection(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    original = "alpha\nbeta\n"
    modified = "alpha\nbeta\ngamma\n"
    (base / "conflict.txt").write_text(original, encoding="utf-8")

    diff_body = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile="conflict.txt",
            tofile="conflict.txt",
            lineterm="\n",
        )
    )
    patch = f"*** Update File: conflict.txt\n{diff_body}"

    # Modify file to introduce conflict before applying patch
    (base / "conflict.txt").write_text("alpha\nBETA\n", encoding="utf-8")

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="conflict.txt", patch=patch)).content)
    assert result["ok"] is False
    assert result["action"] == "Update"
    assert result["path"] == "conflict.txt"
    assert "context mismatch while applying patch" in result["error"]


def test_apply_patch_rejects_binary_patch(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "bin.dat").write_text("data", encoding="utf-8")

    binary_patch = """*** Update File: bin.dat
GIT binary patch
literal 0
Hc$@)s00001
"""

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="bin.dat", patch=binary_patch)).content)
    assert result == {
        "ok": False,
        "action": "Update",
        "path": "bin.dat",
        "error": "binary patches are not supported",
    }


def test_apply_patch_rejects_header_mismatch(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "a.txt").write_text("x\n", encoding="utf-8")

    patch = """*** Update File: other.txt
--- a.txt
+++ a.txt
@@ -1 +1 @@
-x
+y
"""

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="a.txt", patch=patch)).content)
    assert result["ok"] is False
    assert result["action"] == "Update"
    assert result["path"] == "a.txt"
    assert result["error"].startswith("patch header path")
    assert "a.txt" in result["error"]


def test_apply_patch_rejects_unified_path_mismatch(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.chdir(base)

    (base / "a.txt").write_text("line\n", encoding="utf-8")

    patch = """*** Update File: a.txt
--- old.txt
+++ new.txt
@@ -1 +1 @@
-line
+line
"""

    result = json.loads(apply_patch_impl(ApplyPatchInput(file_path="a.txt", patch=patch)).content)
    assert result["ok"] is False
    assert result["action"] == "Update"
    assert result["path"] == "a.txt"
    assert result["error"].startswith("unified diff path")
    assert "old.txt" in result["error"]
