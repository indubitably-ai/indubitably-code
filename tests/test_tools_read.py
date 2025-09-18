from tools_read import read_file_impl


def test_read_file_full(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = read_file_impl({"path": str(target)})

    assert result == "alpha\nbeta\ngamma\n"


def test_read_file_line_range(tmp_path):
    target = tmp_path / "lines.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file_impl({"path": str(target), "offset": 2, "limit": 2})

    assert result == "two\nthree"


def test_read_file_tail(tmp_path):
    target = tmp_path / "tail.txt"
    target.write_text("\n".join(str(i) for i in range(10)), encoding="utf-8")

    result = read_file_impl({"path": str(target), "tail_lines": 3})

    assert result == "7\n8\n9"
