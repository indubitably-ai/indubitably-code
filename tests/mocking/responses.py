"""Shared helpers for constructing mock Anthropic SSE streams and responses."""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence


def sse_event(event_type: str, data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return a plain dict representing a single SSE event.

    The real Anthropic streaming API emits events as JSON payloads with an
    ``event`` field denoting the type. For tests we only need a lightweight
    representation, so we store the ``type`` key directly alongside any payload.
    """
    payload: Dict[str, Any] = {"type": event_type}
    if data:
        payload.update({str(key): value for key, value in data.items()})
    return payload


def ev_content_block_start(
    index: int,
    *,
    block_type: str = "text",
    block: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a ``content_block_start`` event.

    ``block_type`` defaults to ``text`` to match the most common case. Custom
    blocks can be supplied via ``block`` which takes precedence over
    ``block_type``.
    """
    content_block: Dict[str, Any]
    if block is not None:
        content_block = {str(key): value for key, value in block.items()}
    else:
        content_block = {"type": block_type}
        if block_type == "text":
            content_block.setdefault("text", "")
    return sse_event(
        "content_block_start",
        {
            "index": index,
            "content_block": content_block,
        },
    )


def ev_content_block_delta(index: int, text: str) -> Dict[str, Any]:
    """Build a ``content_block_delta`` event for streaming text."""
    return sse_event(
        "content_block_delta",
        {
            "index": index,
            "delta": {"type": "text_delta", "text": text},
        },
    )


def ev_content_block_stop(index: int) -> Dict[str, Any]:
    """Build the ``content_block_stop`` event closing a content block."""
    return sse_event("content_block_stop", {"index": index})


def ev_tool_use(
    tool_use_id: str,
    name: str,
    input_data: Mapping[str, Any],
    *,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a ``tool_use`` content block start event."""
    block = {
        "type": "tool_use",
        "id": tool_use_id,
        "name": name,
        "input": {str(k): v for k, v in input_data.items()},
    }
    data: Dict[str, Any] = {"content_block": block}
    if index is not None:
        data["index"] = index
    return sse_event("content_block_start", data)


def ev_message_stop() -> Dict[str, Any]:
    """Build the ``message_stop`` event signaling the end of a stream."""
    return sse_event("message_stop", {})


def text_block(text: str) -> Dict[str, Any]:
    """Convenience helper that returns a complete text content block."""
    return {"type": "text", "text": text}


def tool_use_block(
    name: str,
    input_payload: Mapping[str, Any],
    *,
    tool_use_id: str,
) -> Dict[str, Any]:
    """Return a tool-use content block matching Anthropic's schema."""
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": name,
        "input": {str(k): v for k, v in input_payload.items()},
    }


def tool_result_block(
    tool_use_id: str,
    content: str,
    *,
    is_error: bool = False,
) -> Dict[str, Any]:
    """Return a tool-result block aligned with ``ContextSession`` expectations."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


@dataclass
class MockAnthropicResponse:
    """Minimal response object returned by :class:`MockAnthropic`.

    The real Anthropic SDK returns ``anthropic.types.Message``. For tests we only
    need the fields that the harness inspects: ``content`` plus a handful of
    metadata attributes that appear in integration tests.
    """

    content: List[Dict[str, Any]] = field(default_factory=list)
    id: str = field(default_factory=lambda: _next_response_id("msg"))
    model: str = "claude-3-mock"
    role: str = "assistant"
    stop_reason: str = "end_turn"
    stop_sequence: Optional[str] = None
    usage: Dict[str, int] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )

    @classmethod
    def from_blocks(cls, blocks: Sequence[Mapping[str, Any]]) -> "MockAnthropicResponse":
        """Create a response directly from already-normalized blocks."""
        normalized = [{str(k): v for k, v in block.items()} for block in blocks]
        return cls(content=normalized)

    @classmethod
    def from_events(cls, events: Sequence[Mapping[str, Any]]) -> "MockAnthropicResponse":
        """Create a response by folding the SSE events emitted by the API."""
        active: MutableMapping[int, Dict[str, Any]] = {}
        text_buffers: MutableMapping[int, List[str]] = {}
        content: List[Dict[str, Any]] = []

        for raw_event in events:
            event = dict(raw_event)
            etype = event.get("type")

            if etype == "content_block_start":
                block = dict(event.get("content_block", {}))
                index = int(event.get("index", len(active)))
                btype = block.get("type")
                if btype == "tool_use":
                    active[index] = {
                        "type": "tool_use",
                        "id": block.get("id") or block.get("tool_use_id"),
                        "name": block.get("name", ""),
                        "input": dict(block.get("input", {})),
                    }
                elif btype == "tool_result":
                    active[index] = {
                        "type": "tool_result",
                        "tool_use_id": block.get("tool_use_id") or block.get("id", ""),
                        "content": block.get("content", ""),
                        "is_error": bool(block.get("is_error", False)),
                    }
                else:  # treat everything else as text
                    text_buffers[index] = [block.get("text", "")]
                    active[index] = {"type": "text", "text": block.get("text", "")}

            elif etype == "content_block_delta":
                index = int(event.get("index", 0))
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_buffers.setdefault(index, []).append(delta.get("text", ""))
                    active.setdefault(index, {"type": "text", "text": ""})
                    active[index]["text"] = "".join(text_buffers[index])

            elif etype == "content_block_stop":
                index = int(event.get("index", 0))
                block = active.pop(index, None)
                if block is not None:
                    content.append(block)
                text_buffers.pop(index, None)

            elif etype == "message_stop":
                break

        # Flush any remaining blocks in index order to mimic streaming finish.
        for index in sorted(active):
            block = active[index]
            if block["type"] == "text":
                block["text"] = "".join(text_buffers.get(index, [block.get("text", "")]))
            content.append(block)

        return cls(content=content)

    def clone(self) -> "MockAnthropicResponse":
        """Return a deep-ish copy safe for reuse across tests."""
        return MockAnthropicResponse(
            content=[json.loads(json.dumps(block)) for block in self.content],
            id=self.id,
            model=self.model,
            role=self.role,
            stop_reason=self.stop_reason,
            stop_sequence=self.stop_sequence,
            usage=dict(self.usage),
        )


_counter = itertools.count()


def _next_response_id(prefix: str) -> str:
    return f"{prefix}_{next(_counter)}"


__all__ = [
    "MockAnthropicResponse",
    "ev_content_block_delta",
    "ev_content_block_start",
    "ev_content_block_stop",
    "ev_message_stop",
    "ev_tool_use",
    "sse_event",
    "text_block",
    "tool_result_block",
    "tool_use_block",
]
