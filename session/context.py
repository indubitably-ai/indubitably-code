"""High-level session manager orchestrating history, compaction, and pins."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from policies import ExecutionContext
from tools.mcp_pool import MCPClientFactory, MCPClientPool

from .compaction import CompactionEngine
from .history import HistoryStore, MessageRecord
from .pins import PinManager, Pin
from .settings import MCPServerDefinition, SessionSettings
from .summaries import summarize_tool_output
from .telemetry import SessionTelemetry
from .token_meter import TokenMeter


@dataclass
class CompactStatus:
    triggered: bool
    total_tokens: int
    window_tokens: int
    summary: Optional[str] = None


class ContextSession:
    def __init__(
        self,
        settings: SessionSettings,
        *,
        meter: Optional[TokenMeter] = None,
        telemetry: Optional[SessionTelemetry] = None,
        history: Optional[HistoryStore] = None,
        pins: Optional[PinManager] = None,
        mcp_client_factory: Optional[MCPClientFactory] = None,
        mcp_client_ttl: Optional[float] = None,
        mcp_definitions: Optional[Dict[str, MCPServerDefinition]] = None,
    ) -> None:
        self.settings = settings
        self.meter = meter or TokenMeter(settings.model.name)
        self.telemetry = telemetry or SessionTelemetry()
        self.history = history or HistoryStore(self.meter)
        self.pins = pins or PinManager()
        self.compactor = CompactionEngine(self.history, self.settings, self.meter, self.telemetry)
        self.auto_compact = settings.compaction.auto
        self.cwd = Path.cwd()
        self.exec_context = self._build_exec_context(settings)
        self.recent_summary: Optional[str] = None
        self._mcp_pool: Optional[MCPClientPool] = None
        self._mcp_definitions: Dict[str, MCPServerDefinition] = dict(mcp_definitions or {})
        if mcp_client_factory is not None:
            self.configure_mcp_pool(
                mcp_client_factory,
                ttl_seconds=mcp_client_ttl,
                definitions=self._mcp_definitions,
            )

    @classmethod
    def from_settings(
        cls,
        settings: SessionSettings,
        *,
        mcp_client_factory: Optional[MCPClientFactory] = None,
        mcp_client_ttl: Optional[float] = None,
        mcp_definitions: Optional[Dict[str, MCPServerDefinition]] = None,
    ) -> "ContextSession":
        return cls(
            settings,
            mcp_client_factory=mcp_client_factory,
            mcp_client_ttl=mcp_client_ttl,
            mcp_definitions=mcp_definitions,
        )

    def configure_mcp_pool(
        self,
        factory: MCPClientFactory,
        *,
        ttl_seconds: Optional[float] = None,
        definitions: Optional[Dict[str, MCPServerDefinition]] = None,
    ) -> None:
        """Install an MCP client pool for this session."""

        self._mcp_definitions = dict(definitions or {})
        self._mcp_pool = MCPClientPool(factory, ttl_seconds=ttl_seconds)

    async def get_mcp_client(self, server: str) -> Any:
        """Return a pooled MCP client for *server* if pooling is configured."""

        if self._mcp_pool is None:
            return None
        if self._mcp_definitions and server not in self._mcp_definitions:
            return None
        self.telemetry.incr("mcp_fetches")
        return await self._mcp_pool.get_client(server)

    async def mark_mcp_client_unhealthy(self, server: str) -> None:
        """Evict the cached client for *server* after an error."""

        if self._mcp_pool is None:
            return
        await self._mcp_pool.mark_unhealthy(server)

    async def close(self) -> None:
        """Release pooled resources associated with the session."""

        if self._mcp_pool is not None:
            await self._mcp_pool.shutdown()
        self._mcp_pool = None

    def register_system_text(self, text: str) -> None:
        self.history.register_system(text, priority=0)
        self._update_counters()

    def add_user_message(self, text: str) -> MessageRecord:
        record = self.history.register_user(text, priority=0)
        self._after_change()
        return record

    def add_assistant_message(self, blocks: List[Dict[str, Any]]) -> MessageRecord:
        record = self.history.register_assistant(blocks, priority=1)
        self._after_change()
        return record

    def add_tool_results(self, tool_blocks: List[Dict[str, Any]], *, dedupe: bool = True) -> Optional[MessageRecord]:
        payload = str(tool_blocks)
        if dedupe and self.history.has_tool_hash(payload):
            return None
        record = self.history.register_tool_results(tool_blocks, priority=1)
        self.history.register_tool_hash(payload, record)
        self._after_change()
        return record

    def add_tool_text_result(self, tool_use_id: str, text: str, *, is_error: bool) -> Optional[MessageRecord]:
        block = self.build_tool_result_block(tool_use_id, text, is_error=is_error)
        # Always emit the tool result to satisfy the Anthropic API requirement
        # that every tool_use is immediately followed by a tool_result message.
        return self.add_tool_results([block], dedupe=False)

    def build_tool_result_block(self, tool_use_id: str, text: str, *, is_error: bool) -> Dict[str, Any]:
        truncated = self._truncate_tool_text(text)
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": truncated,
            "is_error": is_error,
        }

    def rollback_last_turn(self) -> None:
        self.history.rollback_current_turn()
        self._update_counters()

    def force_compact(self) -> CompactStatus:
        triggered = self.compactor.maybe_compact(force=True)
        self.recent_summary = self.history.summary_record.content[0]["text"] if self.history.summary_record else None
        self._update_counters()
        return CompactStatus(
            triggered=triggered,
            total_tokens=self.history.total_tokens(),
            window_tokens=self.settings.model.window_tokens,
            summary=self.recent_summary,
        )

    def maybe_compact(self) -> Optional[CompactStatus]:
        if not self.auto_compact:
            self._update_counters()
            return None
        triggered = self.compactor.maybe_compact()
        if triggered:
            self.recent_summary = self.history.summary_record.content[0]["text"] if self.history.summary_record else None
        self._update_counters()
        if not triggered:
            return None
        return CompactStatus(
            triggered=True,
            total_tokens=self.history.total_tokens(),
            window_tokens=self.settings.model.window_tokens,
            summary=self.recent_summary,
        )

    def build_messages(self) -> List[Dict[str, Any]]:
        base = list(self.history.messages())
        pin_blocks = self._build_pin_blocks()
        if pin_blocks:
            system_count = sum(1 for message in base if message["role"] == "system")
            base = base[:system_count] + [{"role": "system", "content": pin_blocks}] + base[system_count:]
        self._update_counters()
        return base

    def status(self) -> Dict[str, Any]:
        tokens = self.history.total_tokens()
        window = self.settings.model.window_tokens
        pct = (tokens / window * 100) if window else 0.0
        return {
            "tokens": tokens,
            "window": window,
            "usage_pct": round(pct, 2),
            "auto_compact": self.auto_compact,
            "keep_last_turns": self.settings.compaction.keep_last_turns,
            "last_compaction": self.history.last_compaction_timestamp,
            "pins": [self._pin_to_dict(pin) for pin in self.pins.list_pins()],
            "telemetry": self.telemetry.snapshot(),
        }

    def update_setting(self, dotted_key: str, value: Any) -> SessionSettings:
        self.settings = self.settings.update_with(**{dotted_key: value})
        self.compactor.settings = self.settings
        self.auto_compact = self.settings.compaction.auto
        self.exec_context = self._build_exec_context(self.settings)
        self._update_counters()
        return self.settings

    def add_pin(self, text: str, *, ttl_seconds: Optional[int] = None) -> Pin:
        pin = self.pins.add_pin(text, ttl_seconds=ttl_seconds)
        self.telemetry.set("pins_size", self.pins.size())
        return pin

    def remove_pin(self, identifier: str) -> bool:
        removed = self.pins.remove_pin(identifier)
        self.telemetry.set("pins_size", self.pins.size())
        return removed

    def _pin_to_dict(self, pin: Pin) -> Dict[str, Any]:
        return {
            "id": pin.identifier,
            "text": pin.text,
            "expires_at": pin.expires_at,
        }

    def _truncate_tool_text(self, text: str) -> str:
        limits = self.settings.tools
        bytes_len = len(text.encode("utf-8"))
        lines = text.splitlines()
        if bytes_len <= limits.max_stdout_bytes and len(lines) <= limits.max_lines:
            return text
        return summarize_tool_output(text, max_lines=limits.max_lines)

    def _build_pin_blocks(self) -> List[Dict[str, Any]]:
        pins = list(self.pins.list_pins())
        if not pins:
            return []
        budget = max(self.settings.compaction.pin_budget_tokens, 1)
        used = 0
        blocks: List[Dict[str, Any]] = []
        for pin in pins:
            text = f"[pin:{pin.identifier}] {pin.text}"
            candidate = {"type": "text", "text": text}
            tokens = self.meter.estimate_messages([{"role": "system", "content": [candidate]}])
            if used + tokens > budget:
                blocks.append({"type": "text", "text": "[pin-summary] additional pins omitted"})
                break
            blocks.append(candidate)
            used += tokens
        self.telemetry.set("pins_size", len(pins))
        return blocks

    def _build_exec_context(self, settings: SessionSettings) -> ExecutionContext:
        execution = settings.execution
        allowed_paths = execution.allowed_paths or None
        blocked_commands = execution.blocked_commands or None
        return ExecutionContext(
            cwd=self.cwd,
            sandbox_policy=execution.sandbox,
            approval_policy=execution.approval,
            allowed_paths=allowed_paths,
            blocked_commands=blocked_commands,
            timeout_seconds=execution.timeout_seconds,
        )

    def _after_change(self) -> None:
        status = self.maybe_compact()
        if status is None:
            self._update_counters()

    def _update_counters(self) -> None:
        self.telemetry.set("tokens_used", self.history.total_tokens())


__all__ = ["ContextSession", "CompactStatus"]
