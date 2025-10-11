import json

from tools.output import (
    ExecOutput,
    MODEL_FORMAT_MAX_BYTES,
    format_exec_output,
)


def test_format_exec_output_returns_full_output_when_within_limits():
    payload = ExecOutput(exit_code=0, duration_seconds=0.02, output="hello\n")
    result = json.loads(format_exec_output(payload))

    assert result["output"] == "hello\n"
    assert result["metadata"]["exit_code"] == 0
    assert result["metadata"]["timed_out"] is False


def test_format_exec_output_truncates_and_marks_large_output():
    large_output = "".join(f"line {i}\n" for i in range(1000))
    payload = ExecOutput(exit_code=1, duration_seconds=1.5, output=large_output)

    result = json.loads(format_exec_output(payload))

    assert "Total output lines: 1000" in result["output"]
    assert "[... omitted" in result["output"]
    assert len(result["output"].encode("utf-8")) <= MODEL_FORMAT_MAX_BYTES


def test_format_exec_output_marks_timeouts():
    payload = ExecOutput(exit_code=-1, duration_seconds=5.25, output="", timed_out=True)
    result = json.loads(format_exec_output(payload))

    assert result["metadata"]["timed_out"] is True
    assert result["metadata"]["exit_code"] == -1
    assert result["output"].startswith("command timed out after 5.2")
