"""Telemetry collector for session metrics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class SessionTelemetry:
    counters: Dict[str, int] = field(default_factory=lambda: {
        "tokens_used": 0,
        "compact_events": 0,
        "drops_count": 0,
        "summarizer_calls": 0,
        "pins_size": 0,
        "mcp_fetches": 0,
    })

    def incr(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def set(self, key: str, value: int) -> None:
        self.counters[key] = value

    def snapshot(self) -> Dict[str, int]:
        return dict(self.counters)


__all__ = ["SessionTelemetry"]
