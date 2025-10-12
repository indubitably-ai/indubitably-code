from commands import handle_slash_command
from session import (
    CompactionSettings,
    ContextSession,
    ExecutionPolicySettings,
    ModelSettings,
    SessionSettings,
)
from policies import ApprovalPolicy, SandboxPolicy


def _make_settings(*, keep_last: int = 1) -> SessionSettings:
    return SessionSettings(
        model=ModelSettings(name="test", context_tokens=256, guardrail_tokens=32),
        compaction=CompactionSettings(auto=True, keep_last_turns=keep_last, target_tokens=160),
    )


def test_default_model_window_matches_sonnet_guardrail():
    settings = SessionSettings()
    assert settings.model.name == "claude-sonnet-4-5"
    assert settings.model.context_tokens == 200_000
    assert settings.model.guardrail_tokens == 20_000
    assert settings.model.window_tokens == 180_000


def test_context_session_compacts_when_forced():
    session = ContextSession(_make_settings(keep_last=1))
    session.register_system_text("system guidance")

    for idx in range(4):
        session.add_user_message(f"user turn {idx} discussing goals and constraints for idx {idx}")
        session.add_assistant_message([{"type": "text", "text": f"assistant reply {idx} with TODO item"}])

    status = session.force_compact()
    assert session.history.summary_record is not None
    assert status.summary
    assert session.history.total_tokens() <= session.settings.model.window_tokens
    messages = session.build_messages()
    assert any(msg["role"] == "assistant" and "Goals" in msg["content"][0]["text"] for msg in messages if msg["content"])


def test_slash_commands_manage_pins_and_status():
    session = ContextSession(_make_settings(keep_last=2))
    session.add_user_message("initial request touching file foo.py and TODO: refactor")
    session.add_assistant_message([{"type": "text", "text": "acknowledged"}])
    session.update_setting("compaction.keep_last_turns", "1")

    handled, message = handle_slash_command("/pin add --ttl=30 remember config", session)
    assert handled is True
    assert "Pinned" in message

    handled, status_message = handle_slash_command("/status", session)
    assert handled is True
    assert "Pins" in status_message

    handled, compact_msg = handle_slash_command("/compact", session)
    assert handled is True
    assert "Compaction" in compact_msg

    pins = list(session.pins.list_pins())
    assert pins and pins[0].text.startswith("remember")

    handled, unpin_msg = handle_slash_command(f"/unpin {pins[0].identifier}", session)
    assert handled is True
    assert "Removed" in unpin_msg

    handled, unknown = handle_slash_command("/unknown", session)
    assert handled is True
    assert "Unknown" in unknown


def test_tool_result_dedupe_cleared_on_rollback():
    session = ContextSession(_make_settings())
    session.register_system_text("system")

    session.add_user_message("search for compaction logic")
    session.add_assistant_message([
        {"type": "tool_use", "id": "toolu_demo", "name": "codebase_search", "input": {"query": "compaction"}},
    ])

    first_record = session.add_tool_text_result("toolu_demo", "first-result", is_error=False)
    assert first_record is not None

    session.rollback_last_turn()

    session.add_user_message("search for compaction logic")
    session.add_assistant_message([
        {"type": "tool_use", "id": "toolu_demo", "name": "codebase_search", "input": {"query": "compaction"}},
    ])

    second_record = session.add_tool_text_result("toolu_demo", "first-result", is_error=False)
    assert second_record is not None

    messages = session.build_messages()
    assert any(
        msg["role"] == "user"
        and msg["content"]
        and msg["content"][0].get("type") == "tool_result"
        and msg["content"][0].get("tool_use_id") == "toolu_demo"
        for msg in messages
    )


def test_context_session_exec_context_updates_with_settings():
    settings = SessionSettings(
        execution=ExecutionPolicySettings(
            sandbox=SandboxPolicy.STRICT,
            approval=ApprovalPolicy.ALWAYS,
        )
    )
    session = ContextSession(settings)
    assert session.exec_context.sandbox_policy == SandboxPolicy.STRICT

    session.update_setting("execution.approval", "never")
    assert session.exec_context.approval_policy == ApprovalPolicy.NEVER
