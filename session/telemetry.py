"""Telemetry collector for session metrics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import json


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
    })
    tool_executions: List[ToolExecutionEvent] = field(default_factory=list)
    tool_execution_times: Dict[str, List[float]] = field(default_factory=dict)
    tool_error_counts: Dict[str, int] = field(default_factory=dict)
    parallel_tool_batches: int = 0

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

    def export_otel(self) -> str:
        records = []
        for event in self.tool_executions:
            records.append(
                {
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
                    },
                }
            )
        return json.dumps({"events": records}, ensure_ascii=False, indent=2)


__all__ = ["SessionTelemetry", "ToolExecutionEvent"]
