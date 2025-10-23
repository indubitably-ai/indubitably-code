"""Interactive Anthropic agent with tool support for local development."""

import asyncio
import logging
import os
import select
import sys
import json
import re
import textwrap
import time
import threading
from pathlib import Path
from typing import Callable, Dict, Any, List, Iterable, Optional, Set, TextIO
from anthropic import Anthropic, RateLimitError
from pyfiglet import Figlet
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from tools.tool_summary import summarize_tool_call, truncate_text

from agents_md import load_agents_md
from config import load_anthropic_config
from commands import handle_slash_command
from input_handler import InputHandler
from prompt import PromptPacker, PackedPrompt
from session import ContextSession, TurnDiffTracker, load_session_settings
from tools import (
    ConfiguredToolSpec,
    ToolCallRuntime,
    ToolRouter,
    ToolSpec,
    build_registry_from_tools,
    MCPHandler,
    connect_stdio_server,
)


try:  # pragma: no cover - platform guard
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows fallback
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]


ToolFunc = Callable[..., str]


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        fn: ToolFunc,
        *,
        capabilities: Optional[Iterable[str]] = None,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.fn = fn
        self.capabilities: Set[str] = set(capabilities or [])

    def to_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
logger = logging.getLogger(__name__)


class EscapeListener:
    """Detects ESC key presses while keeping normal line input usable."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._orig_attrs: Optional[List[Any]] = None
        self._fd: Optional[int] = None

        isatty = getattr(stream, "isatty", None)
        if callable(isatty):
            try:
                stream_is_tty = bool(isatty())
            except Exception:  # pragma: no cover - defensive
                stream_is_tty = False
        else:
            stream_is_tty = False

        self._available = termios is not None and tty is not None and stream_is_tty

        if self._available:
            try:
                self._fd = stream.fileno()
            except (AttributeError, ValueError, OSError):  # pragma: no cover - defensive
                self._available = False

    def arm(self) -> bool:
        if not self._available:
            return False
        if self._thread and self._thread.is_alive():
            return True

        assert self._fd is not None  # nosec - guarded by _available
        try:
            self._orig_attrs = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:  # pragma: no cover - defensive
            self._available = False
            return False

        self._event.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch, name="esc-listener", daemon=True)
        self._thread.start()
        return True

    def disarm(self) -> None:
        if not self._available:
            return

        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=0.2)
        self._thread = None

        if self._fd is not None and self._orig_attrs is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._orig_attrs)
            except Exception:  # pragma: no cover - defensive
                pass
        self._orig_attrs = None
        self._stop_event.clear()
        self._event.clear()

    def consume_triggered(self) -> bool:
        if not self._available:
            return False
        if self._event.is_set():
            self._event.clear()
            return True
        return False

    def _watch(self) -> None:
        if self._fd is None:
            return
        try:
            while not self._stop_event.is_set():
                try:
                    rlist, _, _ = select.select([self._fd], [], [], 0.1)
                except (OSError, ValueError):  # pragma: no cover - defensive
                    break
                if not rlist:
                    continue
                try:
                    data = os.read(self._fd, 1)
                except OSError:  # pragma: no cover - defensive
                    break
                if data == b"\x1b":
                    self._event.set()
                    break
        finally:
            self._stop_event.set()


class StatusJournal:
    """Append-only status log that groups messages by section."""

    _STATE_STYLES = {
        "pending": "yellow",
        "ok": "green",
        "error": "red",
        "warn": "bright_yellow",
        "info": "cyan",
    }

    def __init__(
        self,
        *,
        transcript_path: Optional[str],
        use_color: bool,
        console: Optional[Console] = None,
    ) -> None:
        self._transcript_path = transcript_path
        self._seen_sections: List[str] = []
        self._section_set: Set[str] = set()
        self._console = console or Console(no_color=not use_color, highlight=False, soft_wrap=False)
        self._use_color = use_color

    def reset(self) -> None:
        if self._seen_sections:
            self._emit(Text(""))
        self._seen_sections = []
        self._section_set.clear()

    def record(self, section: str, message: str, *, state: str = "info") -> None:
        if section not in self._section_set:
            if self._seen_sections:
                self._emit(Text(""))
            heading_style = "bold cyan" if self._use_color else ""
            heading = Text(f"• {section}", style=heading_style)
            self._emit(heading)
            self._section_set.add(section)
            self._seen_sections.append(section)

        state_style = self._STATE_STYLES.get(state, self._STATE_STYLES["info"])
        row = Text("  └ ", style="dim" if self._use_color else "")
        if message:
            row.append(Text(message, style=state_style if self._use_color else ""))
        self._emit(row)

    def _emit(self, text: Text) -> None:
        self._console.print(text)
        _print_transcript(self._transcript_path, text.plain)


def run_agent(
    tools: List["Tool"],
    *,
    use_color: bool = True,
    transcript_path: Optional[str] = None,
    debug_tool_use: bool = False,
    tool_debug_log_path: Optional[str] = None,
) -> None:
    config = load_anthropic_config()
    session_settings = load_session_settings()

    mcp_definitions = {definition.name: definition for definition in session_settings.mcp.definitions}
    mcp_enabled = bool(session_settings.mcp.enable and mcp_definitions)

    def _build_mcp_factory():
        async def factory(server: str) -> Any:
            definition = mcp_definitions.get(server)
            if definition is None:
                raise ValueError(f"unknown MCP server '{server}'")
            return await connect_stdio_server(definition)

        return factory

    def _compute_mcp_ttl() -> Optional[float]:
        durations = [d.ttl_seconds for d in mcp_definitions.values() if d.ttl_seconds is not None]
        if not durations:
            return None
        return min(durations)

    context = ContextSession.from_settings(
        session_settings,
        mcp_client_factory=_build_mcp_factory() if mcp_enabled else None,
        mcp_client_ttl=_compute_mcp_ttl() if mcp_enabled else None,
        mcp_definitions=mcp_definitions if mcp_enabled else None,
    )
    agents_doc = load_agents_md()
    if agents_doc:
        context.register_system_text(agents_doc.system_text())
    packer = PromptPacker(context)
    client = Anthropic()
    debug_log_path = Path(tool_debug_log_path).expanduser().resolve() if tool_debug_log_path else None
    tool_event_counter = 0
    configured_specs, registry = build_registry_from_tools(tools)
    tool_router = ToolRouter(registry, configured_specs)
    tool_runtime = ToolCallRuntime(tool_router)
    tool_defs = [spec.spec.to_anthropic_definition() for spec in configured_specs]
    tool_map = {tool.name: tool for tool in tools}
    registered_mcp_tools: Set[str] = set()

    def _sanitize_mcp_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        from tools.mcp_integration import MCPToolDiscovery

        discovery = MCPToolDiscovery()
        return discovery._sanitize_json_schema(dict(schema))  # type: ignore[attr-defined]

    def _register_mcp_tool_spec(spec: ToolSpec) -> None:
        if spec.name in registered_mcp_tools:
            return

        registry.register_handler(spec.name, MCPHandler())
        configured = ConfiguredToolSpec(spec, supports_parallel=False)
        configured_specs.append(configured)
        tool_router.register_spec(configured)
        tool_defs.append(spec.to_anthropic_definition())
        registered_mcp_tools.add(spec.name)

    async def _discover_mcp_tools() -> None:
        for server_name in mcp_definitions:
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
                spec = ToolSpec(
                    name=fq_name,
                    description=getattr(tool, "description", "") or "",
                    input_schema=_sanitize_mcp_schema(getattr(tool, "inputSchema", {}) or {}),
                )
                _register_mcp_tool_spec(spec)

    if mcp_enabled:
        try:
            asyncio.run(_discover_mcp_tools())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_discover_mcp_tools())
            finally:
                loop.close()
    CYAN = "[96m" if use_color else ""
    GREEN = "[92m" if use_color else ""
    YELLOW = "[93m" if use_color else ""
    RED = "[91m" if use_color else ""
    BOLD = "[1m" if use_color else ""
    DIM = "[2m" if use_color else ""
    RESET = "[0m" if use_color else ""
    console = Console(no_color=not use_color, highlight=False, soft_wrap=False)
    figlet = Figlet(font="standard")
    ascii_art = figlet.renderText("INDUBITABLY CODE")
    art_lines = ascii_art.rstrip("\n").split("\n")
    max_len = max((len(line) for line in art_lines), default=0)
    horizontal_border = "+" + "=" * (max_len + 2) + "+"

    _print_transcript(transcript_path, ascii_art)

    print(CYAN + horizontal_border + RESET if use_color else horizontal_border)
    for line in art_lines:
        if use_color:
            print(CYAN + "| " + line.ljust(max_len) + " |" + RESET)
        else:
            print("| " + line.ljust(max_len) + " |")
    print((CYAN + horizontal_border + RESET) if use_color else horizontal_border)
    print("Type your prompt and press Enter (ctrl-c to quit)\n")
    read_user = True

    backoff_seconds = 2.0
    rate_limit_retries = 0
    listener = EscapeListener(sys.stdin)

    turn_index = 0

    last_logged_turn: Optional[str] = None

    journal = (
        StatusJournal(transcript_path=transcript_path, use_color=use_color, console=console)
        if not debug_tool_use
        else None
    )

    # Initialize input handler with history support
    input_handler = InputHandler()

    try:
        while True:
            added_user_this_turn = False
            current_turn_label = f"Turn {turn_index + 1}"
            if read_user:
                listener.disarm()
                status_snapshot = context.status()
                _print_prompt_menu(DIM, RESET, status_snapshot)
                try:
                    stripped = input_handler.get_input(f"{BOLD}You ▸ {RESET}")
                except EOFError:
                    # User pressed Ctrl+D
                    break
                if not stripped:
                    read_user = True
                    continue
                handled, command_message = handle_slash_command(stripped, context)
                if handled:
                    if command_message:
                        output = f"{YELLOW}{command_message}{RESET}" if use_color else command_message
                        print(output)
                        _print_transcript(transcript_path, f"COMMAND: {command_message}")
                    read_user = True
                    continue
                context.add_user_message(stripped)
                added_user_this_turn = True
                _print_transcript(transcript_path, f"USER: {stripped}")
                listener.arm()
            else:
                listener.arm()

            if listener.consume_triggered():
                _notify_manual_interrupt(YELLOW, RESET, transcript_path, use_color)
                read_user = True
                continue

            try:
                if journal and last_logged_turn != current_turn_label:
                    journal.reset()
                    last_logged_turn = current_turn_label
                packed = packer.pack()
                if debug_tool_use:
                    _debug_print_prompt(packed, YELLOW, RESET, use_color)
                request_kwargs: Dict[str, Any] = {
                    "model": config.model,
                    "max_tokens": config.max_tokens,
                    "messages": packed.messages,
                    "tools": tool_defs,
                }
                if packed.system:
                    request_kwargs["system"] = packed.system
                if journal:
                    journal.record(current_turn_label, "Anthropic request started", state="pending")
                msg = client.messages.create(**request_kwargs)
                if journal:
                    journal.record(
                        current_turn_label,
                        f"Anthropic response received ({len(msg.content)} blocks)",
                        state="ok",
                    )
                backoff_seconds = 2.0
                rate_limit_retries = 0
            except RateLimitError as exc:  # pragma: no cover - requires live API
                if journal:
                    journal.record(
                        current_turn_label,
                        f"Rate limited; retrying in {min(backoff_seconds, 30.0):.1f}s",
                        state="warn",
                    )
                wait = min(backoff_seconds, 30.0)
                print(
                    f"Anthropic rate limit hit; retrying in {wait:.1f}s... ({exc})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                backoff_seconds = min(backoff_seconds * 2, 60.0)
                rate_limit_retries += 1
                if rate_limit_retries > 5:
                    print("Rate limit retries exhausted; aborting current turn.", file=sys.stderr)
                    if added_user_this_turn:
                        context.rollback_last_turn()
                    read_user = True
                    backoff_seconds = 2.0
                    rate_limit_retries = 0
                    continue
                read_user = False
                continue
            except Exception as exc:  # pragma: no cover - surfaced to user
                if journal:
                    journal.record(current_turn_label, f"Anthropic error: {exc}", state="error")
                print(f"Anthropic error: {exc}", file=sys.stderr)
                if added_user_this_turn:
                    context.rollback_last_turn()
                read_user = True
                continue

            assistant_blocks = _normalize_content(msg.content)
            context.add_assistant_message(assistant_blocks)
            turn_index += 1
            setattr(context, "turn_index", turn_index)

            turn_tracker = TurnDiffTracker(turn_id=turn_index)

            interrupted = False
            interrupt_notified = False
            encountered_tool = False
            tool_results_content: List[Dict[str, Any]] = []
            pending_calls: List[tuple] = []

            fatal_event = False
            for block_dict in assistant_blocks:
                if not interrupted and listener.consume_triggered():
                    interrupted = True
                    if not interrupt_notified:
                        _notify_manual_interrupt(YELLOW, RESET, transcript_path, use_color)
                        interrupt_notified = True

                btype = block_dict.get("type")
                if btype == "text":
                    text = block_dict.get("text", "")
                    _print_assistant_text(
                        text,
                        GREEN,
                        RESET,
                        console=console,
                        use_color=use_color,
                    )
                    _print_transcript(transcript_path, f"SAMUS: {text}")
                elif btype == "tool_use":
                    encountered_tool = True
                    tool_name = block_dict.get("name", "")
                    tool_input = block_dict.get("input", {})
                    tool_summary = summarize_tool_call(tool_name, tool_input)
                    tool_use_id = block_dict.get("id") or block_dict.get("tool_use_id", "tool")
                    call = tool_router.build_tool_call(block_dict)
                    if journal:
                        label = tool_summary or (tool_name or "tool")
                        journal.record(current_turn_label, f"{label} requested", state="info")

                    _print_tool_invocation(
                        tool_name,
                        tool_input,
                        CYAN,
                        YELLOW,
                        RESET,
                        verbose=debug_tool_use,
                    )

                    if call is None:
                        result_str = "unrecognized tool payload"
                        is_error = True
                        tool_skipped = False
                        _print_tool_result(result_str, is_error, RED if is_error else GREEN, RESET, verbose=debug_tool_use)
                        transcript_label = "ERROR" if is_error else "RESULT"
                        _print_transcript(transcript_path, f"TOOL {tool_name} {transcript_label}: {result_str}")
                        if journal:
                            label = tool_summary or (tool_name or "tool")
                            journal.record(
                                current_turn_label,
                                f"{label} failed: unrecognized payload",
                                state="error",
                            )
                        tool_block = context.build_tool_result_block(
                            tool_use_id,
                            result_str,
                            is_error=is_error,
                        )
                        tool_results_content.append(tool_block)
                        _record_tool_debug_event(
                            debug_tool_use,
                            debug_log_path,
                            turn=tool_event_counter + 1,
                            tool_name=tool_name,
                            payload=tool_input,
                            result=result_str,
                            is_error=is_error,
                            skipped=tool_skipped,
                        )
                        tool_event_counter += 1
                        continue

                    impl = next((t for t in tools if t.name == tool_name), None)
                    is_mcp_tool = tool_name in registered_mcp_tools
                    if impl is None and not is_mcp_tool:
                        result_str = "tool not found"
                        is_error = True
                        tool_skipped = False
                        _print_tool_result(result_str, is_error, RED if is_error else GREEN, RESET, verbose=debug_tool_use)
                        transcript_label = "ERROR" if is_error else "RESULT"
                        _print_transcript(transcript_path, f"TOOL {tool_name} {transcript_label}: {result_str}")
                        if journal:
                            label = tool_summary or (tool_name or "tool")
                            journal.record(
                                current_turn_label,
                                f"{label} failed: not found",
                                state="error",
                            )
                        tool_block = context.build_tool_result_block(
                            tool_use_id,
                            result_str,
                            is_error=is_error,
                        )
                        tool_results_content.append(tool_block)
                        _record_tool_debug_event(
                            debug_tool_use,
                            debug_log_path,
                            turn=tool_event_counter + 1,
                            tool_name=tool_name,
                            payload=tool_input,
                            result=result_str,
                            is_error=is_error,
                            skipped=tool_skipped,
                        )
                        tool_event_counter += 1
                        continue
                    else:
                        tool_skipped = interrupted
                        if interrupted:
                            result_str = "tool execution skipped due to user interrupt"
                            is_error = True
                            _print_tool_result(result_str, is_error, RED if is_error else GREEN, RESET, verbose=debug_tool_use)
                            transcript_label = "ERROR" if is_error else "RESULT"
                            _print_transcript(transcript_path, f"TOOL {tool_name} {transcript_label}: {result_str}")
                            if journal:
                                label = tool_summary or (tool_name or "tool")
                                journal.record(
                                    current_turn_label,
                                    f"{label} skipped: user interrupt",
                                    state="warn",
                                )
                            tool_block = context.build_tool_result_block(
                                tool_use_id,
                                result_str,
                                is_error=is_error,
                            )
                            tool_results_content.append(tool_block)
                            _record_tool_debug_event(
                                debug_tool_use,
                                debug_log_path,
                                turn=tool_event_counter + 1,
                                tool_name=tool_name,
                                payload=tool_input,
                                result=result_str,
                                is_error=is_error,
                                skipped=tool_skipped,
                            )
                            tool_event_counter += 1
                            continue

                        pending_calls.append((call, tool_name, tool_input, tool_use_id, tool_summary))
                        if journal:
                            label = tool_summary or (tool_name or "tool")
                            journal.record(
                                current_turn_label,
                                f"{label} queued for execution",
                                state="pending",
                            )

            if tool_results_content:
                context.add_tool_results(tool_results_content, dedupe=False)
                tool_results_content = []

            if pending_calls:
                async def _run_pending() -> List[Dict[str, Any]]:
                    # Telemetry: record size of this parallel batch
                    try:
                        if hasattr(context, "telemetry"):
                            context.telemetry.incr("parallel_batches", 1)
                            context.telemetry.incr("parallel_batch_tools_total", len(pending_calls))
                    except Exception:
                        pass
                    tasks = [
                        tool_runtime.execute_tool_call(
                            session=context,
                            turn_context=context,
                            tracker=turn_tracker,
                            sub_id="cli",
                            call=call,
                        )
                        for (call, *_rest) in pending_calls
                    ]
                    return await asyncio.gather(*tasks)

                results = asyncio.run(_run_pending())
                for result, (call, tool_name, tool_input, tool_use_id, tool_summary) in zip(results, pending_calls):
                    is_error = bool(result.get("is_error"))
                    result_str = str(result.get("content", ""))
                    _print_tool_result(result_str, is_error, RED if is_error else GREEN, RESET, verbose=debug_tool_use)
                    transcript_label = "ERROR" if is_error else "RESULT"
                    _print_transcript(transcript_path, f"TOOL {tool_name} {transcript_label}: {result_str}")
                    if journal:
                        state = "error" if is_error else "ok"
                        preview = truncate_text(result_str.strip(), limit=80)
                        label = tool_summary or (tool_name or "tool")
                        message = f"{label} {'error' if is_error else 'completed'}"
                        if preview:
                            message = f"{message}: {preview}"
                        journal.record(current_turn_label, message, state=state)

                    # Preserve preformatted tool result content/metadata as provided by runtime
                    tool_block = {
                        "type": "tool_result",
                        "tool_use_id": call.call_id,
                        "content": result_str,
                        "is_error": is_error,
                    }
                    metadata = result.get("metadata")
                    if metadata:
                        tool_block["metadata"] = dict(metadata)
                        if "error_type" in metadata and metadata["error_type"]:
                            tool_block["error_type"] = metadata["error_type"]
                    context.add_tool_results([tool_block], dedupe=False)

                    _record_tool_debug_event(
                        debug_tool_use,
                        debug_log_path,
                        turn=tool_event_counter + 1,
                        tool_name=tool_name,
                        payload=tool_input,
                        result=result_str,
                        is_error=is_error,
                        skipped=False,
                    )
                    tool_event_counter += 1

                    if result.get("error_type") == "fatal" or (metadata and metadata.get("error_type") == "fatal"):
                        fatal_event = True

                pending_calls = []

            if fatal_event:
                if journal:
                    journal.record(current_turn_label, "Fatal tool error encountered", state="error")
                print("Fatal tool error encountered; stopping session.", file=sys.stderr)
                break

            if interrupted and not interrupt_notified:
                _notify_manual_interrupt(YELLOW, RESET, transcript_path, use_color)
                interrupt_notified = True

            if interrupted or not encountered_tool:
                read_user = True
            else:
                read_user = False
    except KeyboardInterrupt:
        friendly = "Goodbye!"
        if journal:
            journal.reset()
            journal.record("Session", friendly, state="info")
        else:
            style = "bold yellow" if use_color else ""
            console.print(Text(friendly, style=style))
        _print_transcript(transcript_path, f"SYSTEM: {friendly}")
    finally:
        listener.disarm()
        input_handler.cleanup()
        try:
            # Flush telemetry to OTEL (JSONL) if export is enabled in session settings
            try:
                tel_cfg = getattr(context.settings, "telemetry", None)
                if (
                    tel_cfg is not None
                    and getattr(tel_cfg, "enable_export", False)
                    and getattr(tel_cfg, "export_path", None)
                ):
                    try:
                        from session.otel import OtelExporter as _OtelExporter
                        exporter = _OtelExporter(
                            service_name=tel_cfg.service_name,
                            path=tel_cfg.export_path,
                        )
                        context.telemetry.flush_to_otel(exporter)
                    except Exception as exc:
                        logger.debug("Telemetry export failed: %s", exc)
            except Exception as exc:
                logger.debug("Telemetry export configuration failed: %s", exc)
            asyncio.run(context.close())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(context.close())
            finally:
                loop.close()


if __name__ == "__main__":
    from run import main as run_main

    run_main()


def _normalize_content(blocks: Iterable[Any]) -> List[Dict[str, Any]]:
    return [_normalize_block(block) for block in blocks]


def _normalize_block(block: Any) -> Dict[str, Any]:
    btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
    if isinstance(block, dict):
        base = dict(block)
        base.setdefault("type", btype or "text")
        return base
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




def _print_assistant_text(
    text: str,
    color: str,
    reset: str,
    width: int = 80,
    *,
    console: Optional[Console] = None,
    use_color: bool = True,
) -> None:
    if not text:
        return
    if console is not None:
        header_style = "bold green" if use_color else ""
        console.print(Text("Samus ▸", style=header_style))
        console.print(Markdown(text))
        console.print()
        return
    formatted = _format_assistant_text(text, width=width)
    print(f"{color}Samus ▸{reset}\n{formatted}\n")


def _print_tool_invocation(
    name: str,
    payload: Any,
    label_color: str,
    key_color: str,
    reset: str,
    *,
    verbose: bool,
) -> None:
    summary = summarize_tool_call(name, payload)
    label = summary or name
    print(f"{label_color}⚙️  Tool ▸ {label}{reset}")
    if not verbose:
        return
    if isinstance(payload, dict) and payload:
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False)
            else:
                rendered = str(value)
            print(f"  {key_color}{key}{reset}: {rendered}")


def _print_tool_result(
    message: str,
    is_error: bool,
    color: str,
    reset: str,
    *,
    verbose: bool,
    width: int = 78,
) -> None:
    if not verbose and not is_error:
        return
    prefix = "error" if is_error else "result"
    wrapped = textwrap.fill(message, width=width)
    print(f"{color}  ↳ {prefix}:{reset} {wrapped}")


def _print_transcript(path: Optional[str], line: str) -> None:
    if not path or not line:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")
    except Exception:
        return


def _record_tool_debug_event(
    enabled: bool,
    log_path: Optional[Path],
    *,
    turn: int,
    tool_name: str,
    payload: Any,
    result: str,
    is_error: bool,
    skipped: bool,
) -> None:
    if not enabled:
        return
    event = {
        "turn": turn,
        "tool": tool_name,
        "input": _jsonable(payload),
        "result": result,
        "is_error": is_error,
        "skipped": skipped,
        "paths": _extract_paths(payload),
    }
    if log_path:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass


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


def _format_assistant_text(text: str, width: int = 80) -> str:
    lines: List[str] = []
    for raw_paragraph in text.split("\n"):
        paragraph = raw_paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        bullet_match = re.match(r"^(\d+\.|[-*•])\s+(.*)", paragraph)
        if bullet_match:
            prefix, body = bullet_match.groups()
            indent = " " * (len(prefix) + 1)
            wrapped = textwrap.fill(
                body,
                width=width,
                initial_indent=f"{prefix} ",
                subsequent_indent=indent,
            )
        else:
            wrapped = textwrap.fill(paragraph, width=width)
        lines.append(wrapped)
    return "\n".join(lines).rstrip()


def _print_prompt_menu(dim: str, reset: str, status: Optional[Dict[str, Any]] = None) -> None:
    base = f"{dim}Send ↵  •  /status  •  /compact  •  Quit Ctrl+C{reset}" if dim or reset else "Send ↵  •  /status  •  /compact  •  Quit Ctrl+C"
    print(base)
    if not status:
        return
    tokens = status.get("tokens", 0)
    window = status.get("window", 0)
    remaining = max(window - tokens, 0) if isinstance(window, (int, float)) else 0
    if isinstance(window, (int, float)) and window > 0:
        context_pct = round(max(remaining / window * 100, 0.0), 2)
        context_pct_str = f"{context_pct:.0f}" if context_pct.is_integer() else f"{context_pct:.2f}".rstrip('0').rstrip('.')
        context_display = f"{context_pct_str}% Context left"
    else:
        context_display = "Context left n/a"
    metrics = f"{dim}Tokens {tokens}/{window}  •  {context_display}{reset}" if dim or reset else f"Tokens {tokens}/{window}  •  {context_display}"
    print(metrics)


def _debug_print_prompt(packed: "PackedPrompt", color: str, reset: str, use_color: bool) -> None:
    prefix = color if use_color else ""
    suffix = reset if use_color else ""
    print(f"{prefix}[prompt-debug] system blocks: {len(packed.system)}{suffix}")
    for idx, msg in enumerate(packed.messages):
        role = msg.get("role")
        kinds = ",".join(block.get("type", "?") for block in msg.get("content", []))
        print(f"{prefix}[prompt-debug] {idx}: role={role} blocks=[{kinds}]{suffix}")


def _notify_manual_interrupt(color: str, reset: str, transcript_path: Optional[str], use_color: bool) -> None:
    message = "Agent paused; add guidance or press Enter to resume."
    if color and use_color:
        print(f"{color}⏸  {message}{reset}")
    else:
        print(f"⏸  {message}")
    _print_transcript(transcript_path, "INTERRUPT: agent paused by user")
