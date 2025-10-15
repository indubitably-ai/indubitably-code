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
        """Serialize events and write ONE JSON line per event.

        The line format is:
        {"resource": {"service.name": "..."}, "event": { ...single event... }}
        """

        # Serialize each event on its own line for robust downstream processing
        lines: list[str] = []
        resource = dict(self._resource)
        for event in events:
            line = json.dumps({"resource": resource, "event": event}, ensure_ascii=False)
            lines.append(line)

        if not lines:
            return

        if self._sink is not None:
            with self._lock:
                for line in lines:
                    self._sink.write(line + "\n")
                self._sink.flush()
            return
        if self._path is not None:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    for line in lines:
                        fh.write(line + "\n")
            return
        with self._lock:
            self._buffer.extend(lines)

    def buffered_payloads(self) -> list[str]:
        """Return any payloads retained in memory (used when no sink/path provided)."""

        with self._lock:
            return list(self._buffer)


__all__ = ["OtelExporter"]
