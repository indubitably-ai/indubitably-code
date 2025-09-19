import sys
import types

import pytest

from agent import run_agent, Tool


def test_run_agent_transcript_records(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.log"

    tool = Tool(
        name="echo",
        description="",
        input_schema={"type": "object"},
        fn=lambda payload: "ok",
    )

    class DummyClient:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **_):
            messages = [
                types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(type="text", text="hello"),
                        types.SimpleNamespace(type="tool_use", name="echo", input={}, id="1"),
                    ]
                ),
                types.SimpleNamespace(
                    content=[types.SimpleNamespace(type="text", text="done")]
                ),
            ]
            if self.calls >= len(messages):
                raise RuntimeError("no more responses")
            result = messages[self.calls]
            self.calls += 1
            return result

    class DummyStdin:
        def __init__(self):
            self._values = ["hi\n", ""]

        def readline(self):
            return self._values.pop(0) if self._values else ""

    monkeypatch.setattr("agent.Anthropic", lambda: DummyClient())
    monkeypatch.setattr("sys.stdin", DummyStdin())

    # Suppress banner printing to keep test output quiet
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

    run_agent([tool], use_color=False, transcript_path=str(transcript))

    contents = transcript.read_text(encoding="utf-8")
    assert "USER: hi" in contents
    assert "SAMUS: hello" in contents
    assert "TOOL echo RESULT: ok" in contents
    assert "SAMUS: done" in contents


def _run_agent_with_dummy_io(monkeypatch, *, debug_tool_use: bool, tool_fn, payload):
    tool = Tool(
        name="echo",
        description="",
        input_schema={"type": "object"},
        fn=tool_fn,
    )

    responses = [
        types.SimpleNamespace(
            content=[
                types.SimpleNamespace(type="tool_use", name="echo", input=payload, id="1"),
            ]
        ),
        types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="done")]
        ),
    ]

    class DummyClient:
        def __init__(self):
            self.messages = self
            self._responses = list(responses)
            self._index = 0

        def create(self, **_):
            if self._index >= len(self._responses):
                raise RuntimeError("no more responses")
            result = self._responses[self._index]
            self._index += 1
            return result

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

    monkeypatch.setattr("agent.Anthropic", lambda: DummyClient())
    monkeypatch.setattr("agent.Figlet", lambda font="standard": DummyFiglet(font))
    monkeypatch.setattr("sys.stdin", DummyStdin())

    run_agent([tool], use_color=False, debug_tool_use=debug_tool_use)


def test_run_agent_hides_tool_details_when_debug_disabled(monkeypatch, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        return "ok"

    _run_agent_with_dummy_io(monkeypatch, debug_tool_use=False, tool_fn=tool_fn, payload=payload)
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ result" not in captured.out
    assert "payload_key" not in captured.out
    assert "UNIQUE_PAYLOAD_VALUE" not in captured.out


def test_run_agent_shows_tool_details_when_debug_enabled(monkeypatch, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        return "ok"

    _run_agent_with_dummy_io(monkeypatch, debug_tool_use=True, tool_fn=tool_fn, payload=payload)
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ result" in captured.out
    assert "payload_key" in captured.out
    assert "UNIQUE_PAYLOAD_VALUE" in captured.out


def test_run_agent_shows_errors_without_debug(monkeypatch, capsys):
    payload = {"payload_key": "UNIQUE_PAYLOAD_VALUE"}

    def tool_fn(_payload):
        raise RuntimeError("boom failure")

    _run_agent_with_dummy_io(monkeypatch, debug_tool_use=False, tool_fn=tool_fn, payload=payload)
    captured = capsys.readouterr()

    assert "⚙️  Tool ▸ echo" in captured.out
    assert "↳ error" in captured.out
    assert "boom failure" in captured.out
