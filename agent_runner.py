"""Headless agent runner with tool auditing and policy controls."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from anthropic import Anthropic

from agent import Tool
from config import load_anthropic_config


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
    ) -> None:
        self.options = options
        self.config = load_anthropic_config()
        self.client = client or Anthropic()
        self.all_tools = list(tools)
        self.active_tools = self._filter_tools()
        self.tool_map = {tool.name: tool for tool in self.active_tools}
        self.tool_events: List[ToolEvent] = []
        self.edited_files: Set[str] = set()

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

        conversation: List[Dict[str, Any]] = [
            *(initial_conversation or []),
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ]

        text_outputs: List[str] = []
        stopped_reason = "completed"

        for turn_idx in range(1, self.options.max_turns + 1):
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                messages=conversation,
                tools=[tool.to_definition() for tool in self.active_tools],
            )

            conversation.append({"role": "assistant", "content": response.content})

            tool_results_content: List[Dict[str, Any]] = []
            encountered_tool = False
            tool_error = False

            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_outputs.append(getattr(block, "text", ""))
                elif getattr(block, "type", None) == "tool_use":
                    encountered_tool = True
                    event, tool_result = self._handle_tool_use(block, turn_idx)
                    tool_results_content.append(tool_result)
                    tool_error = tool_error or event.is_error

            if not encountered_tool:
                turns_used = turn_idx
                break

            conversation.append({"role": "user", "content": tool_results_content})

            if tool_error and self.options.exit_on_tool_error:
                stopped_reason = "tool_error"
                turns_used = turn_idx
                break
        else:
            # max turns exhausted
            turns_used = self.options.max_turns
            stopped_reason = "max_turns"

        return AgentRunResult(
            final_response="\n".join(txt for txt in text_outputs if txt).strip(),
            tool_events=self.tool_events,
            edited_files=sorted(self.edited_files),
            turns_used=turns_used,
            stopped_reason=stopped_reason,
            conversation=conversation,
        )

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

    def _handle_tool_use(self, block: Any, turn_idx: int) -> tuple[ToolEvent, Dict[str, Any]]:
        tool_name = getattr(block, "name", "")
        tool_input = getattr(block, "input", {})
        tool_use_id = getattr(block, "id", f"tool-{turn_idx}")
        tool = self.tool_map.get(tool_name)

        skipped = False
        is_error = False
        result_str = ""

        if tool is None:
            is_error = True
            result_str = f"tool '{tool_name}' not permitted"
        elif self.options.dry_run:
            skipped = True
            is_error = True
            result_str = "dry-run: execution skipped"
        else:
            try:
                result_str = tool.fn(tool_input)
            except Exception as exc:  # pragma: no cover - defensive
                is_error = True
                result_str = str(exc)

        if tool is not None and not is_error and not skipped:
            for path in _extract_paths(tool_input):
                self.edited_files.add(path)
                self._write_change_record(tool_name, path, result_str)
        elif tool is not None and tool.capabilities and "write_fs" in tool.capabilities:
            for path in _extract_paths(tool_input):
                # Track attempted writes even if failing to aid auditing.
                self.edited_files.add(path)

        event = ToolEvent(
            turn=turn_idx,
            tool_name=tool_name,
            raw_input=tool_input,
            result=result_str,
            is_error=is_error,
            skipped=skipped,
            paths=_extract_paths(tool_input),
        )
        self.tool_events.append(event)
        self._write_audit_event(event)
        self._handle_tool_debug(event)

        tool_result = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result_str,
            "is_error": is_error,
        }

        return event, tool_result

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
