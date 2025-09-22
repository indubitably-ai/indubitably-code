"""Compaction policy orchestrator."""
from __future__ import annotations

from typing import Iterable

from .history import HistoryStore, MessageRecord
from .settings import SessionSettings
from .summaries import summarize_conversation, summarize_tool_output
from .telemetry import SessionTelemetry
from .token_meter import TokenMeter


class CompactionEngine:
    def __init__(
        self,
        history: HistoryStore,
        settings: SessionSettings,
        meter: TokenMeter,
        telemetry: SessionTelemetry,
    ) -> None:
        self.history = history
        self.settings = settings
        self.meter = meter
        self.telemetry = telemetry

    def maybe_compact(self, *, force: bool = False) -> bool:
        self._enforce_tool_limits()

        window = self.settings.model.window_tokens
        target = min(self.settings.compaction.target_tokens, window)
        threshold = int(window * 0.95)
        budget = min(target, threshold)
        current_tokens = self.history.total_tokens()

        if not force and current_tokens <= budget:
            return False

        keep_turns = max(self.settings.compaction.keep_last_turns, 0)
        cutoff_turn = max(self.history.turn_counter - keep_turns + 1, 1)

        candidates = [
            record
            for record in self.history.raw_records()
            if record.kind in {"user", "assistant", "tool_result"}
            and record.turn_id < cutoff_turn
        ]

        if not candidates:
            return False

        summary_text = summarize_conversation(candidates)
        self.telemetry.incr("summarizer_calls")

        before_count = len(list(self.history.raw_records()))

        summary_turn_id = max(cutoff_turn - 1, 0)
        self.history.compact_summary(summary_text, turn_id=summary_turn_id, priority=1)

        self.history.drop_turns_before(cutoff_turn)

        records_after_drop = list(self.history.raw_records())
        system_count = sum(1 for record in records_after_drop if record.kind == "system")
        self.history.reposition_summary(system_count)

        after_count = len(records_after_drop)
        removed = max(0, before_count - after_count)
        if removed:
            self.telemetry.incr("drops_count", removed)

        self.telemetry.incr("compact_events")
        return True

    def _enforce_tool_limits(self) -> None:
        limits = self.settings.tools
        for record in self.history.raw_records():
            if record.kind != "tool_result":
                continue
            text = "\n".join(record.text_fragments())
            if not text:
                continue
            shape_tokens = self.meter.estimate_text(text)
            oversized = shape_tokens > limits.max_tool_tokens or len(text.encode("utf-8")) > limits.max_stdout_bytes
            line_count = text.count("\n") + 1
            if not oversized and line_count <= limits.max_lines:
                self.history.clear_compacted_content(record)
                continue
            truncated = summarize_tool_output(text, max_lines=limits.max_lines)
            self.history.set_compacted_content(record, text=truncated)

    def dry_run_report(self) -> dict[str, int]:
        return {
            "total_tokens": self.history.total_tokens(),
        }


__all__ = ["CompactionEngine"]
