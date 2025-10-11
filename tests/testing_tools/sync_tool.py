"""Test-only tool implementations for exercising timing scenarios."""
from __future__ import annotations

import json
import time
from threading import Lock
from typing import Any, Dict

from agent import Tool


class _ThreadBarrierRegistry:
    def __init__(self) -> None:
        self._barriers: Dict[str, Any] = {}
        self._lock = Lock()

    def get(self, barrier_id: str, parties: int):
        import threading

        with self._lock:
            barrier = self._barriers.get(barrier_id)
            if barrier is None:
                barrier = threading.Barrier(parties)
                self._barriers[barrier_id] = barrier
            elif barrier.parties != parties:
                raise ValueError(
                    f"Barrier '{barrier_id}' configured for {barrier.parties} parties (got {parties})"
                )
            return barrier

    def clear(self) -> None:
        with self._lock:
            self._barriers.clear()


_barriers = _ThreadBarrierRegistry()


def reset_sync_tool_state() -> None:
    """Reset internal barrier registry between tests."""
    _barriers.clear()


def make_sync_test_tool(name: str = "test_sync_tool") -> Tool:
    """Return a tool that can simulate latency and optional synchronization."""

    def impl(payload: Dict[str, Any]) -> str:
        sleep_ms = int(payload.get("sleep_after_ms", 0) or 0)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        barrier_cfg = payload.get("barrier")
        synced = False
        if barrier_cfg:
            barrier = _barriers.get(barrier_cfg["id"], int(barrier_cfg["participants"]))
            barrier.wait()
            synced = True

        return json.dumps({"ok": True, "synced": synced})

    return Tool(
        name=name,
        description="Test-only sync tool",
        input_schema={
            "type": "object",
            "properties": {
                "sleep_after_ms": {"type": "integer"},
                "barrier": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "participants": {"type": "integer"},
                    },
                },
            },
        },
        fn=impl,
        capabilities={"write_fs"},
    )
