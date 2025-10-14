"""Headless agent runner with tool auditing and policy controls."""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set

from anthropic import Anthropic, RateLimitError

from agent import Tool
from agents_md import load_agents_md
from config import load_anthropic_config
from prompt import PromptPacker, PackedPrompt
from session import ContextSession, SessionSettings, TurnDiffTracker, load_session_settings, MCPServerDefinition
from tools import (
    ConfiguredToolSpec,
    ToolCall,
    ToolCallRuntime,
    ToolRouter,
    ToolSpec,
    build_registry_from_tools,
    MCPHandler,
    connect_stdio_server,
)


@dataclass
class ToolEvent:
    turn: int
    tool_name: str
    raw_input: Any
    result: str
    is_error: bool
    skipped: bool
    paths: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "tool": self.tool_name,
            "input": _jsonable(self.raw_input),
            "result": self.result,
            "is_error": self.is_error,
            "skipped": self.skipped,
            "paths": list(self.paths),
            "metadata": dict(self.metadata),
        }


@dataclass
class _PendingToolCall:
    call: ToolCall
    tool: Optional[Tool]
    tool_input: Dict[str, Any]
    tool_use_id: str
    tool_name: str
    turn_idx: int
    tracker: TurnDiffTracker
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    turn_summaries: List[Dict[str, Any]]


class AgentRunner:
    def __init__(
        self,
        tools: Sequence[Tool],
        options: AgentRunOptions,
        *,
        client: Optional[Anthropic] = None,
        session_settings: Optional[SessionSettings] = None,
        mcp_client_factory: Optional[Callable[[str], Awaitable[Any]]] = None,
        mcp_client_ttl: Optional[float] = None,
    ) -> None:
        self.options = options
        self.config = load_anthropic_config()
        self.session_settings = session_settings or load_session_settings()
        self.client = client or Anthropic()
        self._external_mcp_factory = mcp_client_factory
        self._external_mcp_ttl = mcp_client_ttl
        self.all_tools = list(tools)
        self.active_tools = self._filter_tools()
        self.tool_map = {tool.name: tool for tool in self.active_tools}
        self.tool_events: List[ToolEvent] = []
        self.edited_files: Set[str] = set()
        self.context: Optional[ContextSession] = None
        self._packer: Optional[PromptPacker] = None
        self.turn_summaries: List[Dict[str, Any]] = []
        self._turn_trackers: List[TurnDiffTracker] = []

        self._configured_specs, self._tool_registry = build_registry_from_tools(self.active_tools)
        self._tool_router = ToolRouter(self._tool_registry, self._configured_specs)
        self._tool_runtime = ToolCallRuntime(self._tool_router)
        self._tool_definitions = [spec.spec.to_anthropic_definition() for spec in self._configured_specs]

        self._mcp_definitions: Dict[str, MCPServerDefinition] = {
            definition.name: definition for definition in self.session_settings.mcp.definitions
        }
        self._mcp_enabled = bool(
            self._external_mcp_factory or (
                self.session_settings.mcp.enable and self._mcp_definitions
            )
        )
        self._registered_mcp_tools: Set[str] = set()

        if options.allowed_tools:
            known = set(self.tool_map)
            if self._mcp_enabled:
                known |= set(self._mcp_definitions)
            missing = {tool for tool in options.allowed_tools if tool not in known}
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
        self.turn_summaries = []
        self._turn_trackers = []

        definitions = self._mcp_definitions if (self._mcp_enabled and self._mcp_definitions) else None
        context = ContextSession.from_settings(
            self.session_settings,
            mcp_client_factory=self._build_mcp_client_factory() if self._mcp_enabled else None,
            mcp_client_ttl=self._compute_mcp_ttl(),
            mcp_definitions=definitions,
        )
        agents_doc = load_agents_md()
        if agents_doc:
            context.register_system_text(agents_doc.system_text())
        packer = PromptPacker(context)
        self.context = context
        self._packer = packer

        if self._mcp_enabled:
            self._initialize_mcp_support(context)

        if initial_conversation:
            self._seed_context(context, initial_conversation)

        context.add_user_message(prompt.strip())

        text_outputs: List[str] = []
        stopped_reason = "completed"
        turns_used = 0
        should_rollback = True
        fatal_event: Optional[ToolEvent] = None

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

            setattr(context, "turn_index", turn_idx)

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
                        if event.metadata.get("error_type") == "fatal":
                            fatal_event = event
                            stopped_reason = "fatal_tool_error"
                            turns_used = turn_idx
                            break
                        continue

                    if not self._is_tool_allowed(tool_name):
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
                        if event.metadata.get("error_type") == "fatal":
                            fatal_event = event
                            stopped_reason = "fatal_tool_error"
                            turns_used = turn_idx
                            break
                        continue

                    if tool is None and self._is_mcp_tool(tool_name):
                        tool = None
                    elif tool is None:
                        block_result, event = self._record_tool_event(
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_use_id=tool_use_id,
                            result_str=f"tool '{tool_name}' not available",
                            is_error=True,
                            skipped=False,
                            tool=None,
                        )
                        tool_results_content.append(block_result)
                        tool_error = tool_error or event.is_error
                        if event.metadata.get("error_type") == "fatal":
                            fatal_event = event
                            stopped_reason = "fatal_tool_error"
                            turns_used = turn_idx
                            break
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
                        if event.metadata.get("error_type") == "fatal":
                            fatal_event = event
                            stopped_reason = "fatal_tool_error"
                            turns_used = turn_idx
                            break
                        continue

                    call_metadata: Dict[str, Any] = {}
                    if tool is not None and tool.capabilities and "write_fs" in tool.capabilities:
                        exec_context = getattr(context, "exec_context", None)
                        if exec_context and exec_context.requires_approval(tool.name, is_write=True):
                            approved, call_metadata = self._confirm_write_approval(
                                context,
                                tool=tool,
                                tool_input=tool_input,
                            )
                            if not approved:
                                block_result, event = self._record_tool_event(
                                    turn_idx=turn_idx,
                                    tool_name=tool_name,
                                    tool_input=tool_input,
                                    tool_use_id=tool_use_id,
                                    result_str="Tool execution denied by approval policy",
                                    is_error=True,
                                    skipped=True,
                                    tool=tool,
                                    extra_metadata=call_metadata,
                                )
                                tool_results_content.append(block_result)
                                tool_error = tool_error or event.is_error
                                if event.metadata.get("error_type") == "fatal":
                                    fatal_event = event
                                    stopped_reason = "fatal_tool_error"
                                    turns_used = turn_idx
                                    break
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
                            metadata=call_metadata,
                        )
                    )

            if not encountered_tool and not fatal_event:
                turns_used = turn_idx
                break

            if tool_error and self.options.exit_on_tool_error and not fatal_event:
                stopped_reason = "tool_error"
                turns_used = turn_idx
                break

            if pending_calls and not fatal_event:
                runtime_blocks = self._execute_pending_calls(pending_calls)
                for pending, runtime_result in zip(pending_calls, runtime_blocks):
                    updated_block = runtime_result
                    extra_metadata = pending.metadata or None
                    if pending.metadata:
                        merged_meta = dict(runtime_result.get("metadata", {}))
                        merged_meta.update(pending.metadata)
                        updated_block = dict(runtime_result)
                        updated_block["metadata"] = merged_meta
                        if "error_type" not in updated_block and "error_type" in merged_meta:
                            updated_block["error_type"] = merged_meta["error_type"]

                    result_block, event = self._record_tool_event(
                        turn_idx=pending.turn_idx,
                        tool_name=pending.tool_name,
                        tool_input=pending.tool_input,
                        tool_use_id=pending.tool_use_id,
                        result_str=str(updated_block.get("content", "")),
                        is_error=bool(updated_block.get("is_error")),
                        skipped=False,
                        tool=pending.tool,
                        prebuilt_block=updated_block,
                        extra_metadata=extra_metadata,
                    )
                    tool_results_content.append(result_block)
                    tool_error = tool_error or event.is_error
                    if event.metadata.get("error_type") == "fatal":
                        fatal_event = event
                        stopped_reason = "fatal_tool_error"
                        turns_used = pending.turn_idx
                        break

                pending_calls = []

            if tool_results_content:
                context.add_tool_results(tool_results_content, dedupe=False)

            self._log_turn_diff(turn_idx, turn_tracker)
            self._turn_trackers.append(turn_tracker)

            if fatal_event:
                break

            if tool_error and self.options.exit_on_tool_error and not fatal_event:
                stopped_reason = "tool_error"
                turns_used = turn_idx
                break

        else:
            turns_used = self.options.max_turns
            stopped_reason = "max_turns"

        if fatal_event and stopped_reason != "fatal_tool_error":
            stopped_reason = "fatal_tool_error"

        final_response = "\n".join(txt for txt in text_outputs if txt).strip()
        conversation_payload = context.build_messages()

        result = AgentRunResult(
            final_response=final_response,
            tool_events=self.tool_events,
            edited_files=sorted(self.edited_files),
            turns_used=turns_used,
            stopped_reason=stopped_reason,
            conversation=conversation_payload,
            turn_summaries=self.turn_summaries,
        )

        # Ensure session resources are closed and telemetry exports are flushed
        try:
            # Fallback flush in case session-managed exporter wasn't initialized
            tel_cfg = self.session_settings.telemetry
            if getattr(tel_cfg, "enable_export", False) and getattr(tel_cfg, "export_path", None):
                try:
                    from session.otel import OtelExporter as _OtelExporter
                    exporter = _OtelExporter(service_name=tel_cfg.service_name, path=tel_cfg.export_path)
                    context.telemetry.flush_to_otel(exporter)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            import asyncio as _asyncio  # local alias to avoid shadowing
            _asyncio.run(context.close())
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            try:
                loop.run_until_complete(context.close())
            finally:
                loop.close()

        return result

    def undo_last_turn(self) -> List[str]:
        if not self._turn_trackers:
            return []

        tracker = self._turn_trackers.pop()
        operations = tracker.undo()
        if not operations:
            return operations

        if self.turn_summaries:
            self.turn_summaries.pop()

        if self.options.changes_log_path:
            entry = {
                "turn": tracker.turn_id,
                "undo": True,
                "operations": operations,
            }
            entry["paths"] = sorted({str(edit.path) for edit in tracker.edits})
            self.options.changes_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.options.changes_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return operations


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

    def _log_turn_diff(self, turn_idx: int, tracker: TurnDiffTracker) -> None:
        if not tracker.edits:
            return

        paths: Set[str] = set()
        cwd = Path.cwd()
        for edit in tracker.edits:
            resolved = edit.path
            try:
                relative = resolved.resolve().relative_to(cwd)
                paths.add(str(relative))
            except ValueError:
                paths.add(str(resolved.resolve()))

        self.edited_files.update(paths)

        entry = {
            "turn": turn_idx,
            "summary": tracker.generate_summary(),
            "paths": sorted(paths),
        }

        conflict_report = tracker.generate_conflict_report()
        if conflict_report:
            entry["conflicts"] = list(tracker.conflicts)
            entry["conflict_report"] = conflict_report

        diff = tracker.generate_unified_diff()
        if diff:
            entry["diff"] = diff

        self.turn_summaries.append(entry)

        if self.options.changes_log_path:
            self.options.changes_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.options.changes_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


    def _build_mcp_client_factory(self) -> Callable[[str], Awaitable[Any]]:
        if self._external_mcp_factory is not None:
            return self._external_mcp_factory

        async def factory(server: str) -> Any:
            definition = self._mcp_definitions.get(server)
            if definition is None:
                raise ValueError(f"unknown MCP server '{server}'")
            return await connect_stdio_server(definition)

        return factory

    def _compute_mcp_ttl(self) -> Optional[float]:
        if self._external_mcp_ttl is not None:
            return self._external_mcp_ttl
        if not self._mcp_enabled:
            return None
        durations = [d.ttl_seconds for d in self._mcp_definitions.values() if d.ttl_seconds is not None]
        if not durations:
            return None
        return min(durations)

    def _initialize_mcp_support(self, context: ContextSession) -> None:
        async def loader() -> None:
            await self._discover_mcp_tools(context)

        try:
            asyncio.run(loader())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(loader())
            finally:
                loop.close()

    async def _discover_mcp_tools(self, context: ContextSession) -> None:
        if not self._mcp_enabled:
            return

        for server_name in self._mcp_definitions:
            client = await context.get_mcp_client(server_name)
            if client is None:
                continue
            try:
                response = await client.list_tools()
            except Exception:
                await context.mark_mcp_client_unhealthy(server_name)
                continue

            for tool in getattr(response, "tools", []) or []:
                fq_name = f"{server_name}/{tool.name}"
                if fq_name in self._registered_mcp_tools:
                    continue
                schema = getattr(tool, "inputSchema", {}) or {}
                spec = ToolSpec(
                    name=fq_name,
                    description=getattr(tool, "description", "") or "",
                    input_schema=self._sanitize_mcp_schema(schema),
                )
                self._register_mcp_tool_spec(spec)

    def _register_mcp_tool_spec(self, spec: ToolSpec) -> None:
        if spec.name in self._registered_mcp_tools:
            return

        handler = MCPHandler()
        self._tool_registry.register_handler(spec.name, handler)
        configured = ConfiguredToolSpec(spec, supports_parallel=False)
        self._configured_specs.append(configured)
        self._tool_router.register_spec(configured)
        self._tool_definitions.append(spec.to_anthropic_definition())
        self._registered_mcp_tools.add(spec.name)

    def _sanitize_mcp_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        from tools.mcp_integration import MCPToolDiscovery

        discovery = MCPToolDiscovery()
        return discovery._sanitize_json_schema(dict(schema))  # type: ignore[attr-defined]

    def _is_mcp_tool(self, name: str) -> bool:
        if '/' not in name:
            return False
        server, _child = name.split('/', 1)
        return server in self._mcp_definitions

    def _is_tool_allowed(self, tool_name: str) -> bool:
        if tool_name in self.options.blocked_tools:
            return False
        server_prefix = tool_name.split('/', 1)[0] if '/' in tool_name else None
        if server_prefix and server_prefix in self.options.blocked_tools:
            return False

        if not self.options.allowed_tools:
            return True
        if tool_name in self.options.allowed_tools:
            return True
        if server_prefix and server_prefix in self.options.allowed_tools:
            return True
        return False


    async def close(self) -> None:
        """Release resources held by the runner."""

        if self.context is not None:
            await self.context.close()

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
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], ToolEvent]:
        paths = _extract_paths(tool_input)
        metadata: Dict[str, Any] = {}
        if prebuilt_block is not None:
            metadata = dict(prebuilt_block.get("metadata", {}))
        if extra_metadata:
            metadata.update(extra_metadata)
        error_type = metadata.get("error_type")
        if error_type is None and prebuilt_block is not None:
            error_type = prebuilt_block.get("error_type")

        event = ToolEvent(
            turn=turn_idx,
            tool_name=tool_name,
            raw_input=tool_input,
            result=result_str,
            is_error=is_error,
            skipped=skipped,
            paths=paths,
            metadata=metadata,
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

        if metadata:
            block_metadata = dict(block.get("metadata", {}))
            block_metadata.update(metadata)
            block["metadata"] = block_metadata
        if error_type and "error_type" not in block:
            block["error_type"] = error_type

        return block, event

    def _confirm_write_approval(
        self,
        context: ContextSession,
        *,
        tool: Tool,
        tool_input: Dict[str, Any],
    ) -> tuple[bool, Dict[str, Any]]:
        exec_context = getattr(context, "exec_context", None)
        metadata: Dict[str, Any] = {"approval_required": True}
        policy = getattr(exec_context, "approval_policy", None)
        if policy is not None:
            metadata["approval_policy"] = getattr(policy, "value", str(policy))

        paths = _extract_paths(tool_input)
        if paths:
            metadata["approval_paths"] = list(paths)

        approver = getattr(context, "request_approval", None)
        if approver is None:
            metadata["approval_granted"] = False
            metadata["approval_error"] = "no approval callback configured"
            return False, metadata

        try:
            try:
                result = approver(tool_name=tool.name, command=None, paths=list(paths))
            except TypeError:
                result = approver(tool_name=tool.name, command=None)
        except Exception as exc:
            metadata["approval_granted"] = False
            metadata["approval_error"] = str(exc)
            return False, metadata

        resolved = self._resolve_awaitable(result)
        approved = bool(resolved)
        metadata["approval_granted"] = approved
        return approved, metadata

    @staticmethod
    def _resolve_awaitable(result: Any) -> Any:
        if not inspect.isawaitable(result):
            return result
        try:
            return asyncio.run(result)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(result)
            finally:
                asyncio.set_event_loop(None)
                loop.close()


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
