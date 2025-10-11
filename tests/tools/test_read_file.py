import os
from pathlib import Path

import pytest

from tools_read import read_file_impl


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.txt"
    path.write_text("one\nsecond\nthird\nfourth\n", encoding="utf-8")
    return path


def test_read_file_full(sample_file: Path):
    result = read_file_impl({"path": str(sample_file)})
    assert result.startswith("one")
    assert "fourth" in result


def test_read_file_tail_lines(sample_file: Path):
    result = read_file_impl({"path": str(sample_file), "tail_lines": 2})
    assert result.splitlines() == ["third", "fourth"]


def test_read_file_line_range(sample_file: Path):
    result = read_file_impl({"path": str(sample_file), "offset": 2, "limit": 1})
    assert result == "second"


def test_read_file_missing_path_raises():
    with pytest.raises(ValueError):
        read_file_impl({})


def test_read_file_directory_errors(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        read_file_impl({"path": str(tmp_path)})


def test_read_file_byte_range(sample_file: Path):
    result = read_file_impl({"path": str(sample_file), "byte_offset": 4, "byte_limit": 2})
    assert result == "se"
