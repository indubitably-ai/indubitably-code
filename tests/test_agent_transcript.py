import sys

import pytest

from agent import run_agent, Tool
from tests.mocking import MockAnthropic, text_block, tool_use_block


def test_run_agent_transcript_records(tmp_path, anthropic_mock, stdin_stub, monkeypatch):
    transcript = tmp_path / "transcript.log"

    tool = Tool(
        name="echo",
        description="",
        input_schema={"type": "object"},
        fn=lambda payload: "ok",
    )

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()
    client.add_response_from_blocks([
        text_block("hello"),
        tool_use_block("echo", {}, tool_use_id="1"),
    ])
    client.add_response_from_blocks([text_block("done")])

    class DummyFiglet:
        def __init__(self, font: str = "standard") -> None:
            self.font = font

        def renderText(self, text: str) -> str:
            return f"{text}\n"

    monkeypatch.setattr("agent.Figlet", lambda font="standard": DummyFiglet(font))
    stdin_stub("hi\n", "")

    # Suppress banner printing to keep test output quiet
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    run_agent([tool], use_color=False, transcript_path=str(transcript))

    contents = transcript.read_text(encoding="utf-8")
    assert "USER: hi" in contents
    assert "SAMUS: hello" in contents
    assert "TOOL echo RESULT: ok" in contents
    assert "SAMUS: done" in contents


def _run_agent_with_dummy_io(monkeypatch, anthropic_mock, stdin_stub, *, debug_tool_use: bool, tool_fn, payload):
    tool = Tool(
        name="echo",
        description="",
        input_schema={"type": "object"},
        fn=tool_fn,
    )

    class DummyFiglet:
        def __init__(self, font: str = "standard") -> None:
            self.font = font

        def renderText(self, text: str) -> str:
            return f"{text}\n"

    class DummyStdin:
        def __init__(self):
            self._values = ["hello\n", ""]

        def readline(self) -> str:
            return self._values.pop(0) if self._values else ""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()
    client.add_response_from_blocks([
        tool_use_block("echo", payload, tool_use_id="1"),
    ])
    client.add_response_from_blocks([text_block("done")])

    monkeypatch.setattr("agent.Figlet", lambda font="standard": DummyFiglet(font))
    stdin_stub("hello\n", "")

    run_agent([tool], use_color=False, debug_tool_use=debug_tool_use)


def test_run_agent_hides_tool_details_when_debug_disabled(monkeypatch, anthropic_mock, stdin_stub, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        return "ok"

    _run_agent_with_dummy_io(
        monkeypatch,
        anthropic_mock,
        stdin_stub,
        debug_tool_use=False,
        tool_fn=tool_fn,
        payload=payload,
    )
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ result" not in captured.out
    assert "payload_key" not in captured.out
    assert "UNIQUE_PAYLOAD_VALUE" not in captured.out


def test_run_agent_shows_tool_details_when_debug_enabled(monkeypatch, anthropic_mock, stdin_stub, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        return "ok"

    _run_agent_with_dummy_io(
        monkeypatch,
        anthropic_mock,
        stdin_stub,
        debug_tool_use=True,
        tool_fn=tool_fn,
        payload=payload,
    )
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ result" in captured.out
    assert "payload_key" in captured.out
    assert "UNIQUE_PAYLOAD_VALUE" in captured.out


def test_run_agent_shows_errors_without_debug(monkeypatch, anthropic_mock, stdin_stub, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        raise RuntimeError("boom failure")

    _run_agent_with_dummy_io(
        monkeypatch,
        anthropic_mock,
        stdin_stub,
        debug_tool_use=False,
        tool_fn=tool_fn,
        payload=payload,
    )
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ error" in captured.out
    assert "boom failure" in captured.out
