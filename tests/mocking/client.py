"""Anthropic client stub that serves deterministic responses for tests."""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .responses import MockAnthropicResponse


class MockAnthropicMessages:
    """Descriptor object that mimics ``Anthropic.messages`` namespace."""

    def __init__(self, server: "MockAnthropic") -> None:
        self._server = server

    def create(self, **request: Any) -> MockAnthropicResponse:
        """Return the next queued response and record the incoming request."""
        self._server.requests.append(request)
        return self._server._dequeue_response()


class MockAnthropic:
    """Drop-in replacement for ``Anthropic`` in tests."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self._responses: deque[MockAnthropicResponse] = deque()
        self.messages = MockAnthropicMessages(self)

    def add_response(self, response: MockAnthropicResponse) -> None:
        """Queue a response object to be returned on the next ``create`` call."""
        self._responses.append(response.clone())

    def add_response_from_blocks(self, blocks: Sequence[Mapping[str, Any]]) -> None:
        """Convenience helper mirroring ``MockAnthropicResponse.from_blocks``."""
        self.add_response(MockAnthropicResponse.from_blocks(blocks))

    def add_response_from_events(self, events: Sequence[Mapping[str, Any]]) -> None:
        """Queue a response built from SSE events."""
        self.add_response(MockAnthropicResponse.from_events(events))

    def reset(self) -> None:
        """Clear queued responses and recorded requests."""
        self.requests.clear()
        self._responses.clear()

    def _dequeue_response(self) -> MockAnthropicResponse:
        if not self._responses:
            raise RuntimeError("MockAnthropic: no more responses queued")
        response = self._responses.popleft()
        return response.clone()


__all__ = ["MockAnthropic", "MockAnthropicMessages"]
