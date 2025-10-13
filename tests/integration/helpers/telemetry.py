"""Helpers for capturing telemetry exports in integration tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass
class TelemetryEvent:
    """Simple representation of an exported OTEL event."""

    timestamp: str
    attributes: Dict[str, Any]


@dataclass
class TelemetrySink:
    """Collects telemetry events emitted through ``SessionTelemetry.flush_to_otel``."""

    events: List[TelemetryEvent] = field(default_factory=list)

    def export(self, records: Iterable[Dict[str, Any]]) -> None:
        for record in records:
            attributes = dict(record.get("attributes", {}))
            timestamp = str(record.get("timestamp", ""))
            self.events.append(TelemetryEvent(timestamp=timestamp, attributes=attributes))

    def clear(self) -> None:
        self.events.clear()


__all__ = ["TelemetrySink", "TelemetryEvent"]
