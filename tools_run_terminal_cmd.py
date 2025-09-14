import os
import shlex
import json
import time
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Any


_DEF_SHELL = os.environ.get("SHELL") or "/bin/zsh"
_LOG_DIR = Path("run_logs")


def run_terminal_cmd_tool_def() -> dict:
    return {
        "name": "run_terminal_cmd",
        "description": (
            "Propose/execute shell commands. Always prefer non-interactive flags. "
            "If the command is long-running, set is_background=true to run it detached with logs."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command": {"type": "string", "description": "The exact shell command to execute."},
                "is_background": {"type": "boolean", "description": "Run the command detached in the background."},
                "explanation": {"type": "string", "description": "One sentence on why this command is being run."},
            },
            "required": ["command", "is_background"],
        },
    }


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _run_foreground(command: str) -> str:
    # Best-effort to avoid paging: append '| cat' if command likely to use a pager and not already piped
    likely_pages = ["git log", "man ", "less", "more "]
    if not any(tok in command for tok in ["|", ">", "2>"]) and any(p in command for p in likely_pages):
        command = f"{command} | cat"

    completed = subprocess.run(
        command,
        shell=True,
        executable=_DEF_SHELL,
        capture_output=True,
        text=True,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    result = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    return json.dumps(result)


def _run_background(command: str) -> str:
    _ensure_log_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    job_id = f"job-{ts}-{uuid.uuid4().hex[:8]}"

    stdout_path = _LOG_DIR / f"{job_id}.out.log"
    stderr_path = _LOG_DIR / f"{job_id}.err.log"

    stdout_f = open(stdout_path, "w", encoding="utf-8")
    stderr_f = open(stderr_path, "w", encoding="utf-8")

    # Wrap in set -o pipefail for safer pipelines
    wrapped_cmd = f"set -o pipefail; {command}"

    proc = subprocess.Popen(
        wrapped_cmd,
        shell=True,
        executable=_DEF_SHELL,
        stdout=stdout_f,
        stderr=stderr_f,
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        env={**os.environ, "TERM": "xterm-256color"},
    )

    result = {
        "ok": True,
        "job_id": job_id,
        "pid": proc.pid,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "hint": "Follow logs with: tail -f PATH",
    }
    return json.dumps(result)


def run_terminal_cmd_impl(input: Dict[str, Any]) -> str:
    command = input.get("command", "").strip()
    if not command:
        raise ValueError("missing 'command'")

    is_background = bool(input.get("is_background", False))

    # Basic guardrails: discourage obviously interactive programs in foreground
    interactive_bins = {"vim", "nano", "top", "htop", "less", "more"}
    if not is_background:
        try:
            first_bin = shlex.split(command)[0]
            base = os.path.basename(first_bin)
            if base in interactive_bins:
                return json.dumps({
                    "ok": False,
                    "error": f"Refusing to run interactive program '{base}' in foreground; set is_background=true or choose a non-interactive flag.",
                })
        except Exception:
            pass

    return _run_background(command) if is_background else _run_foreground(command)
