"""Helpers for working with :mod:`tests.mocking` Anthropic stubs."""
from __future__ import annotations

from typing import Mapping, Sequence

from tests.mocking import MockAnthropic, text_block, tool_use_block


def queue_tool_turn(
    client: MockAnthropic,
    *,
    tool_name: str,
    payloads: Sequence[Mapping[str, object]],
    final_text: str,
    preamble_text: str = "Working on it.",
) -> None:
    """Enqueue an assistant reply that triggers tool calls followed by a final response."""

    blocks = [text_block(preamble_text)]
    for index, payload in enumerate(payloads, start=1):
        blocks.append(tool_use_block(tool_name, payload, tool_use_id=f"call-{index}"))
    client.add_response_from_blocks(blocks)
    client.add_response_from_blocks([text_block(final_text)])


__all__ = ["queue_tool_turn"]
