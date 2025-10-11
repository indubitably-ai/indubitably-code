"""Mock Anthropic server that wraps the client stub with convenience helpers."""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

from .client import MockAnthropic
from .responses import MockAnthropicResponse


class MockAnthropicServer:
    """Higher-level facade around :class:`MockAnthropic` for streaming tests."""

    def __init__(self) -> None:
        self.client = MockAnthropic()

    # -- Response management -------------------------------------------------

    def add_response(self, events: Iterable[Mapping[str, Any]]) -> None:
        """Queue a streaming response described by SSE events."""
        response = MockAnthropicResponse.from_events(list(events))
        self.client.add_response(response)

    def add_response_from_blocks(self, blocks: Iterable[Mapping[str, Any]]) -> None:
        """Queue a response using already-normalized content blocks."""
        response = MockAnthropicResponse.from_blocks(list(blocks))
        self.client.add_response(response)

    def clear_responses(self) -> None:
        """Remove all queued responses and reset the client queue."""
        self.client.reset()

    # -- Introspection -------------------------------------------------------

    @property
    def requests(self) -> List[Mapping[str, Any]]:
        """Return a snapshot of the recorded API requests."""
        return list(self.client.requests)

    def last_request(self) -> Optional[Mapping[str, Any]]:
        return self.client.requests[-1] if self.client.requests else None

    def get_tool_result(self, tool_use_id: str) -> Mapping[str, Any]:
        """Return the most recent tool-result block for ``tool_use_id``."""
        for request in reversed(self.client.requests):
            messages = request.get("messages", [])
            if not isinstance(messages, list):
                continue
            for message in reversed(messages):
                if not isinstance(message, Mapping):
                    continue
                content = message.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, Mapping) and block.get("type") == "tool_result":
                        if block.get("tool_use_id") == tool_use_id:
                            return dict(block)
        raise KeyError(f"tool_result not found for id '{tool_use_id}'")

    def reset(self) -> None:
        """Clear responses and requests."""
        self.client.reset()
