"""Integration tests that exercise live Anthropic API behaviour."""

from __future__ import annotations

import os

import pytest
from anthropic import Anthropic

from agent_runner import AgentRunOptions, AgentRunner
from config import load_anthropic_config
from prompt import PromptPacker
from session import ContextSession, load_session_settings


pytestmark = pytest.mark.integration


def _require_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is required for integration tests")


@pytest.fixture(scope="session")
def anthropic_client() -> Anthropic:
    _require_api_key()
    return Anthropic()


def _flatten_text(content) -> str:
    """Return concatenated text from content blocks regardless of SDK version."""

    text_chunks = []
    for block in content:
        btype = getattr(block, "type", None)
        if isinstance(block, dict):
            btype = block.get("type")
        if btype == "text":
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                text_chunks.append(text)
    return " ".join(text_chunks)


def test_direct_message_round_trip(anthropic_client: Anthropic) -> None:
    """Smoke test: ensure we can send a basic prompt and receive a response."""

    config = load_anthropic_config()
    session_settings = load_session_settings()
    context = ContextSession.from_settings(session_settings)
    context.register_system_text("You are an automated integration test.")
    context.add_user_message("Reply with the single word 'pong'.")

    packer = PromptPacker(context)
    packed = packer.pack()

    response = anthropic_client.messages.create(
        model=config.model,
        max_tokens=64,
        messages=packed.messages,
        system=packed.system,
    )

    text = _flatten_text(response.content)
    assert "pong" in text.lower()

    usage = getattr(response, "usage", None)
    assert usage is not None
    assert getattr(usage, "input_tokens", 0) > 0
    assert getattr(usage, "output_tokens", 0) > 0


def test_agent_runner_single_turn(anthropic_client: Anthropic) -> None:
    """Ensure AgentRunner can complete a single turn without tool calls."""

    prompt = "Respond with 'integration ok' and do not call tools or ask follow-up questions."
    runner = AgentRunner(
        tools=[],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=anthropic_client,
    )

    result = runner.run(prompt)

    assert "integration ok" in result.final_response.lower()
    assert result.turns_used == 1
    assert not result.tool_events

