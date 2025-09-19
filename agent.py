"""Interactive Anthropic agent with tool support for local development."""

import sys
import json
import re
import textwrap
from pathlib import Path
from typing import Callable, Dict, Any, List, Iterable, Optional, Set
from anthropic import Anthropic
from pyfiglet import Figlet

from config import load_anthropic_config


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
    client = Anthropic()
    conversation: List[Dict[str, Any]] = []
    debug_log_path = Path(tool_debug_log_path).expanduser().resolve() if tool_debug_log_path else None
    tool_event_counter = 0
    CYAN = "\033[96m" if use_color else ""
    GREEN = "\033[92m" if use_color else ""
    YELLOW = "\033[93m" if use_color else ""
    RED = "\033[91m" if use_color else ""
    BOLD = "\033[1m" if use_color else ""
    DIM = "\033[2m" if use_color else ""
    RESET = "\033[0m" if use_color else ""
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

    while True:
        if read_user:
            _print_prompt_menu(DIM, RESET)
            print(f"{BOLD}You ▸ {RESET}", end="", flush=True)
            line = sys.stdin.readline()
            if not line:
                break
            conversation.append({"role": "user", "content": [{"type": "text", "text": line.rstrip('\n')}]})
            _print_transcript(transcript_path, f"USER: {line.rstrip('\n')}")

        tool_defs = [t.to_definition() for t in tools]

        try:
            msg = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                messages=conversation,
                tools=tool_defs,
            )
        except Exception as exc:  # pragma: no cover - surfaced to user
            print(f"Anthropic error: {exc}", file=sys.stderr)
            if conversation and conversation[-1].get("role") == "user":
                conversation.pop()
            read_user = True
            continue

        conversation.append({"role": "assistant", "content": msg.content})

        tool_results_content: List[Dict[str, Any]] = []
        for block in msg.content:
            if block.type == "text":
                _print_assistant_text(block.text, GREEN, RESET)
                _print_transcript(transcript_path, f"SAMUS: {block.text}")
            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

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
                    _print_tool_result("tool not found", True, RED, RESET, verbose=debug_tool_use)
                    _print_transcript(transcript_path, f"TOOL {tool_name} ERROR: not found")
                    tool_results_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "tool not found",
                            "is_error": True,
                        }
                    )
                    _record_tool_debug_event(
                        debug_tool_use,
                        debug_log_path,
                        turn=tool_event_counter + 1,
                        tool_name=tool_name,
                        payload=tool_input,
                        result="tool not found",
                        is_error=True,
                        skipped=False,
                    )
                else:
                    try:
                        result_str = impl.fn(tool_input)
                        _print_tool_result(result_str, False, GREEN, RESET, verbose=debug_tool_use)
                        _print_transcript(transcript_path, f"TOOL {tool_name} RESULT: {result_str}")
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result_str,
                                "is_error": False,
                            }
                        )
                        _record_tool_debug_event(
                            debug_tool_use,
                            debug_log_path,
                            turn=tool_event_counter + 1,
                            tool_name=tool_name,
                            payload=tool_input,
                            result=result_str,
                            is_error=False,
                            skipped=False,
                        )
                    except Exception as e:
                        _print_tool_result(str(e), True, RED, RESET, verbose=debug_tool_use)
                        _print_transcript(transcript_path, f"TOOL {tool_name} ERROR: {e}")
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": str(e),
                                "is_error": True,
                            }
                        )
                        _record_tool_debug_event(
                            debug_tool_use,
                            debug_log_path,
                            turn=tool_event_counter + 1,
                            tool_name=tool_name,
                            payload=tool_input,
                            result=str(e),
                            is_error=True,
                            skipped=False,
                        )

                tool_event_counter += 1

        if not tool_results_content:
            read_user = True
            continue

        conversation.append({"role": "user", "content": tool_results_content})
        read_user = False


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


def _print_prompt_menu(dim: str, reset: str) -> None:
    menu = f"{dim}Send ↵  •  Quit Ctrl+C{reset}" if dim or reset else "Send ↵  •  Quit Ctrl+C"
    print(menu)
