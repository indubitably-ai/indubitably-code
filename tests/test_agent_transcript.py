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
