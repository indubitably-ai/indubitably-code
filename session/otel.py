"""Lightweight helper for exporting telemetry events in an OTEL-friendly format."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Optional, TextIO


class OtelExporter:
    """Emit tool telemetry events to a sink compatible with OTLP JSON payloads."""

    def __init__(
        self,
        *,
        service_name: str = "indubitably-agent",
        sink: Optional[TextIO] = None,
        path: Optional[Path] = None,
        resource: Optional[Mapping[str, str]] = None,
    ) -> None:
        if sink is not None and path is not None:
            raise ValueError("provide either sink or path, not both")
        self._service_name = service_name
        self._sink = sink
        self._path = path
        self._resource: MutableMapping[str, str] = {
            "service.name": service_name,
        }
        if resource:
            self._resource.update({str(k): str(v) for k, v in resource.items()})
        self._lock = threading.Lock()
        self._buffer: list[str] = []

    def export(self, events: Iterable[Mapping[str, object]]) -> None:
        """Serialize *events* and write them to the configured sink."""

        payload = {
            "resource": dict(self._resource),
            "events": list(events),
        }
        serialized = json.dumps(payload, ensure_ascii=False)
        if self._sink is not None:
            with self._lock:
                self._sink.write(serialized + "\n")
                self._sink.flush()
            return
        if self._path is not None:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(serialized + "\n")
            return
        with self._lock:
            self._buffer.append(serialized)

    def buffered_payloads(self) -> list[str]:
        """Return any payloads retained in memory (used when no sink/path provided)."""

        with self._lock:
            return list(self._buffer)


__all__ = ["OtelExporter"]
