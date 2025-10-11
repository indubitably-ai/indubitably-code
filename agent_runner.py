"""Headless agent runner with tool auditing and policy controls."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from anthropic import Anthropic, RateLimitError

from agent import Tool
from agents_md import load_agents_md
from config import load_anthropic_config
from prompt import PromptPacker, PackedPrompt
from session import ContextSession, SessionSettings, TurnDiffTracker, load_session_settings
from tools import ToolCall, ToolCallRuntime, ToolRouter, build_registry_from_tools


@dataclass
class ToolEvent:
    turn: int
    tool_name: str
    raw_input: Any
    result: str
    is_error: bool
    skipped: bool
    paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "tool": self.tool_name,
            "input": _jsonable(self.raw_input),
            "result": self.result,
            "is_error": self.is_error,
            "skipped": self.skipped,
            "paths": list(self.paths),
        }


@dataclass
class _PendingToolCall:
    call: ToolCall
    tool: Tool
    tool_input: Dict[str, Any]
    tool_use_id: str
    tool_name: str
    turn_idx: int
    tracker: TurnDiffTracker


@dataclass
class AgentRunOptions:
    max_turns: int = 8
    exit_on_tool_error: bool = False
    allowed_tools: Optional[Set[str]] = None
    blocked_tools: Set[str] = field(default_factory=set)
    dry_run: bool = False
    audit_log_path: Optional[Path] = None
    changes_log_path: Optional[Path] = None
    verbose: bool = False
    debug_tool_use: bool = False
    tool_debug_log_path: Optional[Path] = None


@dataclass
class AgentRunResult:
    final_response: str
    tool_events: List[ToolEvent]
    edited_files: List[str]
    turns_used: int
    stopped_reason: str
    conversation: List[Dict[str, Any]]


class AgentRunner:
    def __init__(
        self,
        tools: Sequence[Tool],
        options: AgentRunOptions,
        *,
        client: Optional[Anthropic] = None,
        session_settings: Optional[SessionSettings] = None,
    ) -> None:
        self.options = options
        self.config = load_anthropic_config()
        self.session_settings = session_settings or load_session_settings()
        self.client = client or Anthropic()
        self.all_tools = list(tools)
        self.active_tools = self._filter_tools()
        self.tool_map = {tool.name: tool for tool in self.active_tools}
        self.tool_events: List[ToolEvent] = []
        self.edited_files: Set[str] = set()
        self.context: Optional[ContextSession] = None
        self._packer: Optional[PromptPacker] = None

        self._configured_specs, self._tool_registry = build_registry_from_tools(self.active_tools)
        self._tool_router = ToolRouter(self._tool_registry, self._configured_specs)
        self._tool_runtime = ToolCallRuntime(self._tool_router)
        self._tool_definitions = [spec.spec.to_anthropic_definition() for spec in self._configured_specs]

        if options.allowed_tools:
            missing = options.allowed_tools - set(self.tool_map)
            if missing and options.verbose:
                print(f"Warning: allowed tools not available: {sorted(missing)}")

    def run(
        self,
        prompt: str,
        *,
        initial_conversation: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentRunResult:
        if not prompt.strip():
            raise ValueError("prompt must contain text")

        self.tool_events = []
        self.edited_files = set()

        context = ContextSession.from_settings(self.session_settings)
        agents_doc = load_agents_md()
        if agents_doc:
            context.register_system_text(agents_doc.system_text())
        packer = PromptPacker(context)
        self.context = context
        self._packer = packer

        if initial_conversation:
            self._seed_context(context, initial_conversation)

        context.add_user_message(prompt.strip())

        text_outputs: List[str] = []
        stopped_reason = "completed"
        turns_used = 0
        should_rollback = True

        for turn_idx in range(1, self.options.max_turns + 1):
            packed = packer.pack()
            try:
                response = self._call_with_backoff(packed, backoff_seconds=2.0)
            except Exception:
                if should_rollback:
                    context.rollback_last_turn()
                raise

            assistant_blocks = _normalize_content(response.content)
            context.add_assistant_message(assistant_blocks)
            should_rollback = False

            turn_tracker = TurnDiffTracker(turn_id=turn_idx)

            tool_results_content: List[Dict[str, Any]] = []
            tool_error = False
            encountered_tool = False
            pending_calls: List[_PendingToolCall] = []

            for block in assistant_blocks:
                btype = block.get("type")
                if btype == "text":
                    text_outputs.append(block.get("text", ""))
                elif btype == "tool_use":
                    encountered_tool = True
                    block_dict = _normalize_block(block)
                    tool_name = block_dict.get("name", "")
                    tool_input = block_dict.get("input", {}) if isinstance(block_dict.get("input"), dict) else {}
                    tool_use_id = block_dict.get("id") or block_dict.get("tool_use_id", f"tool-{turn_idx}")
                    call = self._tool_router.build_tool_call(block_dict)
                    tool = self.tool_map.get(tool_name)

                    if call is None:
                        block_result, event = self._record_tool_event(
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_use_id=tool_use_id,
                            result_str="unrecognized tool payload",
                            is_error=True,
                            skipped=False,
                            tool=None,
                        )
                        tool_results_content.append(block_result)
                        tool_error = tool_error or event.is_error
                        continue

                    if tool is None:
                        block_result, event = self._record_tool_event(
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_use_id=tool_use_id,
                            result_str=f"tool '{tool_name}' not permitted",
                            is_error=True,
                            skipped=False,
                            tool=None,
                        )
                        tool_results_content.append(block_result)
                        tool_error = tool_error or event.is_error
                        continue

                    if self.options.dry_run:
                        block_result, event = self._record_tool_event(
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_use_id=tool_use_id,
                            result_str="dry-run: execution skipped",
                            is_error=True,
                            skipped=True,
                            tool=tool,
                        )
                        tool_results_content.append(block_result)
                        tool_error = tool_error or event.is_error
                        continue

                    pending_calls.append(
                        _PendingToolCall(
                            call=call,
                            tool=tool,
                            tool_input=tool_input,
                            tool_use_id=tool_use_id,
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            tracker=turn_tracker,
                        )
                    )

            if not encountered_tool:
                turns_used = turn_idx
                break

            if tool_error and self.options.exit_on_tool_error:
                stopped_reason = "tool_error"
                turns_used = turn_idx
                break

            if pending_calls:
                runtime_blocks = self._execute_pending_calls(pending_calls)
                for pending, runtime_result in zip(pending_calls, runtime_blocks):
                    result_block, event = self._record_tool_event(
                        turn_idx=pending.turn_idx,
                        tool_name=pending.tool_name,
                        tool_input=pending.tool_input,
                        tool_use_id=pending.tool_use_id,
                        result_str=str(runtime_result.get("content", "")),
                        is_error=bool(runtime_result.get("is_error")),
                        skipped=False,
                        tool=pending.tool,
                        prebuilt_block=runtime_result,
                    )
                    tool_results_content.append(result_block)
                    tool_error = tool_error or event.is_error

                pending_calls = []

            if tool_results_content:
                context.add_tool_results(tool_results_content, dedupe=False)

            if tool_error and self.options.exit_on_tool_error:
                stopped_reason = "tool_error"
                turns_used = turn_idx
                break

        else:
            turns_used = self.options.max_turns
            stopped_reason = "max_turns"

        final_response = "\n".join(txt for txt in text_outputs if txt).strip()
        conversation_payload = context.build_messages()

        return AgentRunResult(
            final_response=final_response,
            tool_events=self.tool_events,
            edited_files=sorted(self.edited_files),
            turns_used=turns_used,
            stopped_reason=stopped_reason,
            conversation=conversation_payload,
        )


    def _seed_context(self, context: ContextSession, conversation: List[Dict[str, Any]]) -> None:
        auto_state = context.auto_compact
        context.auto_compact = False
        for message in conversation:
            role = message.get("role")
            blocks = _normalize_content(message.get("content", []))
            if role == "system":
                text = _blocks_to_text(blocks)
                if text:
                    context.register_system_text(text)
            elif role == "assistant":
                context.add_assistant_message(blocks)
            elif role == "user":
                if blocks and all(block.get("type") == "tool_result" for block in blocks):
                    context.add_tool_results(blocks, dedupe=False)
                else:
                    text = _blocks_to_text(blocks)
                    if text:
                        context.add_user_message(text)
        context.auto_compact = auto_state
        if auto_state:
            context.maybe_compact()


    def _call_with_backoff(
        self,
        prompt: PackedPrompt,
        backoff_seconds: float,
    ) -> Any:
        wait = backoff_seconds
        retries = 0
        while True:
            try:
                request: Dict[str, Any] = {
                    "model": self.config.model,
                    "max_tokens": self.config.max_tokens,
                    "messages": prompt.messages,
                    "tools": list(self._tool_definitions),
                }
                if prompt.system:
                    request["system"] = prompt.system
                return self.client.messages.create(**request)
            except RateLimitError as exc:  # pragma: no cover - live API scenario
                retries += 1
                if retries > 5:
                    raise
                delay = min(wait, 30.0)
                if self.options.verbose:
                    print(
                        f"Anthropic rate limit hit; retry {retries}/5 in {delay:.1f}s...",
                        file=sys.stderr,
                    )
                time.sleep(delay)
                wait = min(wait * 2, 60.0)

    def _filter_tools(self) -> List[Tool]:
        allowed = self.options.allowed_tools
        blocked = self.options.blocked_tools

        result = []
        for tool in self.all_tools:
            if allowed and tool.name not in allowed:
                continue
            if tool.name in blocked:
                continue
            result.append(tool)
        return result

    def _handle_tool_debug(self, event: ToolEvent) -> None:
        if not self.options.debug_tool_use:
            return
        status = "skipped" if event.skipped else ("error" if event.is_error else "ok")
        payload = json.dumps(_jsonable(event.raw_input), ensure_ascii=False)
        print(
            f"[tool-debug] turn={event.turn} tool={event.tool_name} status={status} input={payload}",
            file=sys.stderr,
        )
        self._write_tool_debug_log(event)

    def _write_audit_event(self, event: ToolEvent) -> None:
        if not self.options.audit_log_path:
            return
        self.options.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.options.audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def _write_tool_debug_log(self, event: ToolEvent) -> None:
        if not self.options.tool_debug_log_path:
            return
        self.options.tool_debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.options.tool_debug_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def _write_change_record(self, tool_name: str, path: str, result: str) -> None:
        if not self.options.changes_log_path:
            return
        self.options.changes_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "tool": tool_name,
            "path": path,
            "result": result,
        }
        with self.options.changes_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _execute_pending_calls(self, pending_calls: List[_PendingToolCall]) -> List[Dict[str, Any]]:
        if not pending_calls:
            return []

        async def _runner() -> List[Dict[str, Any]]:
            tasks = [
                self._tool_runtime.execute_tool_call(
                    session=self.context,
                    turn_context=self.context,
                    tracker=pending.tracker,
                    sub_id=f"turn-{pending.turn_idx}",
                    call=pending.call,
                )
                for pending in pending_calls
            ]
            return await asyncio.gather(*tasks)

        return asyncio.run(_runner())

    def _record_tool_event(
        self,
        *,
        turn_idx: int,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_use_id: str,
        result_str: str,
        is_error: bool,
        skipped: bool,
        tool: Optional[Tool],
        prebuilt_block: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], ToolEvent]:
        paths = _extract_paths(tool_input)
        event = ToolEvent(
            turn=turn_idx,
            tool_name=tool_name,
            raw_input=tool_input,
            result=result_str,
            is_error=is_error,
            skipped=skipped,
            paths=paths,
        )
        self.tool_events.append(event)
        self._write_audit_event(event)
        self._handle_tool_debug(event)

        if tool is not None:
            if not is_error and not skipped:
                for path in paths:
                    self.edited_files.add(path)
                    self._write_change_record(tool.name, path, result_str)
            elif tool.capabilities and "write_fs" in tool.capabilities:
                for path in paths:
                    self.edited_files.add(path)

        if prebuilt_block is not None:
            block = dict(prebuilt_block)
        elif self.context is not None:
            block = self.context.build_tool_result_block(
                tool_use_id,
                result_str,
                is_error=is_error,
            )
        else:
            block = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_str,
                "is_error": is_error,
            }

        return block, event


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _extract_paths(input_payload: Any) -> List[str]:
    if not isinstance(input_payload, dict):
        return []
    keys = ["path", "file_path", "target", "destination"]
    paths: List[str] = []
    for key in keys:
        val = input_payload.get(key)
        if isinstance(val, str):
            paths.append(val)
    return paths


def _normalize_content(blocks: Iterable[Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for block in blocks:
        result.append(_normalize_block(block))
    return result


def _normalize_block(block: Any) -> Dict[str, Any]:
    if isinstance(block, dict):
        return dict(block)
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", getattr(block, "tool_use_id", "")),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}),
        }
    if btype == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": getattr(block, "tool_use_id", getattr(block, "id", "")),
            "content": getattr(block, "content", ""),
            "is_error": getattr(block, "is_error", False),
        }
    data = {"type": btype or "text"}
    for attr in ("id", "name", "text", "content", "input"):
        if hasattr(block, attr):
            data[attr] = getattr(block, attr)
    return data


def _blocks_to_text(blocks: Iterable[Dict[str, Any]]) -> str:
    texts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
    return "\n".join(txt for txt in texts if txt).strip()
