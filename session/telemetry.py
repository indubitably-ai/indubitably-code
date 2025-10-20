"""Telemetry collector for session metrics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:  # pragma: no cover
    from .otel import OtelExporter


@dataclass
class ToolExecutionEvent:
    """Detailed tool execution telemetry event."""

    tool_name: str
    call_id: str
    turn: int
    timestamp: datetime
    duration: float
    success: bool
    error: Optional[str] = None
    input_size: int = 0
    output_size: int = 0
    truncated: bool = False
    error_type: Optional[str] = None
    message: Optional[str] = None
    error_summary: Optional[str] = None
    request_summary: Optional[str] = None
    response_preview: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "call_id": self.call_id,
            "turn": self.turn,
            "timestamp": self.timestamp.isoformat(),
            "duration": self.duration,
            "success": self.success,
            "error": self.error,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "truncated": self.truncated,
            "error_type": self.error_type,
            "message": self.message,
            "error_summary": self.error_summary,
            "request_summary": self.request_summary,
            "response_preview": self.response_preview,
        }


@dataclass
class SessionTelemetry:
    counters: Dict[str, int] = field(default_factory=lambda: {
        "tokens_used": 0,
        "compact_events": 0,
        "drops_count": 0,
        "summarizer_calls": 0,
        "pins_size": 0,
        "mcp_fetches": 0,
        # Policy/approval counters
        "policy_prompts": 0,
        "policy_approved": 0,
        "policy_denied": 0,
        # Parallel execution counters
        "parallel_batches": 0,
        "parallel_batch_tools_total": 0,
    })
    tool_executions: List[ToolExecutionEvent] = field(default_factory=list)
    tool_execution_times: Dict[str, List[float]] = field(default_factory=dict)
    tool_error_counts: Dict[str, int] = field(default_factory=dict)
    parallel_tool_batches: int = 0
    _flushed: bool = False

    def incr(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def set(self, key: str, value: int) -> None:
        self.counters[key] = value

    def snapshot(self) -> Dict[str, int]:
        return dict(self.counters)

    def record_tool_execution(
        self,
        *,
        tool_name: str,
        call_id: str,
        turn: int,
        duration: float,
        success: bool,
        error: Optional[str] = None,
        input_size: int = 0,
        output_size: int = 0,
        truncated: bool = False,
        error_type: Optional[str] = None,
        message: Optional[str] = None,
        error_summary: Optional[str] = None,
        request_summary: Optional[str] = None,
        response_preview: Optional[str] = None,
    ) -> None:
        event = ToolExecutionEvent(
            tool_name=tool_name,
            call_id=call_id,
            turn=turn,
            timestamp=datetime.now(),
            duration=duration,
            success=success,
            error=error,
            input_size=input_size,
            output_size=output_size,
            truncated=truncated,
            error_type=error_type,
            message=message,
            error_summary=error_summary,
            request_summary=request_summary,
            response_preview=response_preview,
        )
        self.tool_executions.append(event)
        self.tool_execution_times.setdefault(tool_name, []).append(duration)
        if not success:
            self.tool_error_counts[tool_name] = self.tool_error_counts.get(tool_name, 0) + 1

    def tool_stats(self, tool_name: str) -> Dict[str, float]:
        times = self.tool_execution_times.get(tool_name, [])
        if not times:
            return {"calls": 0, "errors": 0}
        errors = self.tool_error_counts.get(tool_name, 0)
        calls = len(times)
        return {
            "calls": calls,
            "avg_duration": sum(times) / calls,
            "min_duration": min(times),
            "max_duration": max(times),
            "errors": errors,
            "success_rate": (calls - errors) / calls,
        }

    def iter_otel_events(self) -> Iterable[Dict[str, object]]:
        """Yield OTEL-style event dictionaries for downstream exporters."""

        for event in self.tool_executions:
            yield {
                "timestamp": event.timestamp.isoformat(),
                "name": f"tool.{event.tool_name}",
                "attributes": {
                    "tool.name": event.tool_name,
                    "tool.call_id": event.call_id,
                    "tool.turn": event.turn,
                    "tool.duration_ms": event.duration * 1000,
                    "tool.success": event.success,
                    "tool.error": event.error,
                    "tool.input_bytes": event.input_size,
                    "tool.output_bytes": event.output_size,
                    "tool.truncated": event.truncated,
                    "tool.error_type": event.error_type,
                    "tool.message": event.message,
                    "tool.error_summary": event.error_summary,
                    "tool.request_summary": event.request_summary,
                    "tool.response_preview": event.response_preview,
                },
            }

    def export_otel(self) -> str:
        records = list(self.iter_otel_events())
        return json.dumps({"events": records}, ensure_ascii=False, indent=2)

    def flush_to_otel(self, exporter: "OtelExporter") -> None:
        """Send recorded tool executions to the provided OTEL exporter."""
        if self._flushed:
            return
        exporter.export(self.iter_otel_events())
        self._flushed = True


__all__ = ["SessionTelemetry", "ToolExecutionEvent"]
