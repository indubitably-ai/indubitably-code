"""Interactive Anthropic agent with tool support for local development."""

import sys
import json
import re
import textwrap
import time
from pathlib import Path
from typing import Callable, Dict, Any, List, Iterable, Optional, Set
from anthropic import Anthropic, RateLimitError
from pyfiglet import Figlet

from config import load_anthropic_config
from commands import handle_slash_command
from prompt import PromptPacker
from session import ContextSession, load_session_settings


ToolFunc = Callable[[Dict[str, Any]], str]


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
    context = ContextSession.from_settings(session_settings)
    packer = PromptPacker(context)
    client = Anthropic()
    debug_log_path = Path(tool_debug_log_path).expanduser().resolve() if tool_debug_log_path else None
    tool_event_counter = 0
    CYAN = "[96m" if use_color else ""
    GREEN = "[92m" if use_color else ""
    YELLOW = "[93m" if use_color else ""
    RED = "[91m" if use_color else ""
    BOLD = "[1m" if use_color else ""
    DIM = "[2m" if use_color else ""
    RESET = "[0m" if use_color else ""
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
    while True:
        added_user_this_turn = False
        if read_user:
            status_snapshot = context.status()
            _print_prompt_menu(DIM, RESET, status_snapshot)
            print(f"{BOLD}You ▸ {RESET}", end="", flush=True)
            line = sys.stdin.readline()
            if not line:
                break
            stripped = line.rstrip("\n")
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

        tool_defs = [t.to_definition() for t in tools]

        try:
            packed = packer.pack()
            msg = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                messages=packed.messages,
                tools=tool_defs,
            )
            backoff_seconds = 2.0
            rate_limit_retries = 0
        except RateLimitError as exc:  # pragma: no cover - requires live API
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
            print(f"Anthropic error: {exc}", file=sys.stderr)
            if added_user_this_turn:
                context.rollback_last_turn()
            read_user = True
            continue

        assistant_blocks = _normalize_content(msg.content)
        context.add_assistant_message(assistant_blocks)

        encountered_tool = False
        for block_dict in assistant_blocks:
            btype = block_dict.get("type")
            if btype == "text":
                text = block_dict.get("text", "")
                _print_assistant_text(text, GREEN, RESET)
                _print_transcript(transcript_path, f"SAMUS: {text}")
            elif btype == "tool_use":
                encountered_tool = True
                tool_name = block_dict.get("name", "")
                tool_input = block_dict.get("input", {})
                tool_use_id = block_dict.get("id") or block_dict.get("tool_use_id", "tool")

                _print_tool_invocation(
                    tool_name,
                    tool_input,
                    CYAN,
                    YELLOW,
                    RESET,
                    verbose=debug_tool_use,
                )

                impl = next((t for t in tools if t.name == tool_name), None)
                if impl is None:
                    result_str = "tool not found"
                    is_error = True
                else:
                    try:
                        result_str = impl.fn(tool_input)
                        is_error = False
                    except Exception as exc:  # pragma: no cover - defensive
                        result_str = str(exc)
                        is_error = True

                _print_tool_result(result_str, is_error, RED if is_error else GREEN, RESET, verbose=debug_tool_use)
                transcript_label = "ERROR" if is_error else "RESULT"
                _print_transcript(transcript_path, f"TOOL {tool_name} {transcript_label}: {result_str}")

                context.add_tool_text_result(tool_use_id, result_str, is_error=is_error)

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

        if not encountered_tool:
            read_user = True
        else:
            read_user = False


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




def _print_assistant_text(text: str, color: str, reset: str, width: int = 80) -> None:
    if not text:
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
    print(f"{label_color}⚙️  Tool ▸ {name}{reset}")
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
    usage = status.get("usage_pct", 0.0)
    remaining = max(window - tokens, 0) if isinstance(window, (int, float)) else 0
    metrics = f"{dim}Tokens {tokens}/{window} ({usage}%)  •  Context left {remaining}{reset}" if dim or reset else f"Tokens {tokens}/{window} ({usage}%)  •  Context left {remaining}"
    print(metrics)
