from agents_md import MAX_FILE_BYTES, load_agents_md


def test_load_agents_md_returns_none_when_missing(tmp_path):
    assert load_agents_md(start_dir=tmp_path) is None


def test_load_agents_md_reads_content(tmp_path):
    doc_path = tmp_path / "AGENTS.md"
    doc_path.write_text("Hello Agents", encoding="utf-8")

    result = load_agents_md(start_dir=tmp_path)

    assert result is not None
    assert result.path == doc_path
    assert result.system_text() == "Hello Agents"


def test_load_agents_md_truncates_large_file(tmp_path):
    doc_path = tmp_path / "AGENTS.md"
    doc_path.write_text("x" * (MAX_FILE_BYTES + 256), encoding="utf-8")

    result = load_agents_md(start_dir=tmp_path)

    assert result is not None
    assert len(result.system_text().encode("utf-8")) <= MAX_FILE_BYTES
