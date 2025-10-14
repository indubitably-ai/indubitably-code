"""Session-level configuration for context management and compaction."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from policies import ApprovalPolicy, SandboxPolicy

DEFAULT_CONFIG_PATHS: tuple[Path, ...] = (
    Path.home() / ".agent" / "config.toml",
    Path.home() / ".config" / "indubitably" / "config.toml",
)


@dataclass(frozen=True)
class ModelSettings:
    name: str = "claude-sonnet-4-5"
    context_tokens: int = 200_000
    guardrail_tokens: int = 20_000

    @property
    def window_tokens(self) -> int:
        return max(self.context_tokens - self.guardrail_tokens, 0)


@dataclass(frozen=True)
class CompactionSettings:
    auto: bool = True
    keep_last_turns: int = 4
    target_tokens: int = 110_000
    summarizer: str = "rule_based"
    llm_budget_tokens: int = 0
    pin_budget_tokens: int = 2_048


@dataclass(frozen=True)
class ToolLimitSettings:
    max_tool_tokens: int = 4_000
    max_stdout_bytes: int = 131_072
    max_json_fields: int = 2_000
    max_lines: int = 800


@dataclass
class MCPServerDefinition:
    """Configuration for launching and pooling an MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    cwd: Optional[Path] = None
    encoding: str = "utf-8"
    encoding_errors: str = "strict"
    startup_timeout_ms: Optional[int] = None
    ttl_seconds: Optional[float] = None


@dataclass(frozen=True)
class MCPSettings:
    enable: bool = True
    servers: tuple[str, ...] = ("mcp://local",)
    definitions: tuple[MCPServerDefinition, ...] = ()


@dataclass(frozen=True)
class PrivacySettings:
    no_external_http: bool = False
    redact_pii: bool = True


@dataclass(frozen=True)
class TelemetrySettings:
    """Telemetry/export configuration (OTEL)."""

    enable_export: bool = False
    export_path: Optional[Path] = None
    service_name: str = "indubitably-agent"



@dataclass(frozen=True)
class ExecutionPolicySettings:
    sandbox: SandboxPolicy = SandboxPolicy.RESTRICTED
    approval: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    allowed_paths: tuple[Path, ...] = ()
    blocked_commands: tuple[str, ...] = ()
    timeout_seconds: Optional[float] = None


@dataclass(frozen=True)
class SessionSettings:
    model: ModelSettings = ModelSettings()
    compaction: CompactionSettings = CompactionSettings()
    tools: ToolLimitSettings = ToolLimitSettings()
    mcp: MCPSettings = MCPSettings()
    privacy: PrivacySettings = PrivacySettings()
    execution: ExecutionPolicySettings = ExecutionPolicySettings()
    telemetry: TelemetrySettings = TelemetrySettings()

    def update_with(self, **overrides: Any) -> "SessionSettings":
        """Return new settings with dotted overrides like 'compaction.keep_last_turns'."""

        current: MutableMapping[str, Any] = {
            "model": self.model,
            "compaction": self.compaction,
            "tools": self.tools,
            "mcp": self.mcp,
            "privacy": self.privacy,
            "execution": self.execution,
        }
        updated = dict(current)
        for dotted, raw_value in overrides.items():
            parts = dotted.split(".")
            if len(parts) != 2:
                raise KeyError(f"Override must be of the form group.field (got '{dotted}')")
            group, leaf = parts
            if group not in current:
                raise KeyError(f"Unknown settings group '{group}'")
            target = current[group]
            if not hasattr(target, leaf):
                raise KeyError(f"Unknown field '{leaf}' for settings group '{group}'")
            current_value = getattr(target, leaf)
            cast_value = _cast_value(current_value, raw_value)
            updated[group] = _replace_dataclass(target, {leaf: cast_value})
        return SessionSettings(**updated)


def load_session_settings(path: Optional[Path] = None) -> SessionSettings:
    """Load session settings from *path* or default search locations."""

    config_data: Mapping[str, Any]
    chosen_path: Optional[Path] = None

    if path is not None:
        chosen_path = path.expanduser().resolve()
        config_data = _loads(chosen_path)
    else:
        env_path = os.getenv("INDUBITABLY_SESSION_CONFIG")
        if env_path:
            candidate = Path(env_path).expanduser().resolve()
            if candidate.exists():
                chosen_path = candidate
                config_data = _loads(candidate)
            else:
                config_data = {}
        else:
            for candidate in DEFAULT_CONFIG_PATHS:
                if candidate.exists():
                    chosen_path = candidate
                    config_data = _loads(candidate)
                    break
            else:
                config_data = {}

    return _settings_from_mapping(config_data, base_dir=chosen_path.parent if chosen_path else None)


def _loads(path: Path) -> Mapping[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _settings_from_mapping(mapping: Mapping[str, Any], *, base_dir: Optional[Path]) -> SessionSettings:
    model = ModelSettings()
    model_section = mapping.get("model")
    if isinstance(model_section, Mapping):
        model = _replace_dataclass(
            model,
            {
                "name": model_section.get("name", model.name),
                "context_tokens": int(model_section.get("context_tokens", model.context_tokens)),
                "guardrail_tokens": int(model_section.get("guardrail_tokens", model.guardrail_tokens)),
            },
        )

    compaction = CompactionSettings()
    compaction_section = mapping.get("compaction")
    if isinstance(compaction_section, Mapping):
        compaction = _replace_dataclass(
            compaction,
            {
                "auto": bool(compaction_section.get("auto", compaction.auto)),
                "keep_last_turns": int(compaction_section.get("keep_last_turns", compaction.keep_last_turns)),
                "target_tokens": int(compaction_section.get("target_tokens", compaction.target_tokens)),
                "summarizer": str(compaction_section.get("summarizer", compaction.summarizer)),
                "llm_budget_tokens": int(
                    compaction_section.get("llm_budget_tokens", compaction.llm_budget_tokens)
                ),
                "pin_budget_tokens": int(
                    compaction_section.get("pin_budget_tokens", compaction.pin_budget_tokens)
                ),
            },
        )

    tools = ToolLimitSettings()
    tools_section = _coerce_mapping(mapping.get("tools"))
    if tools_section:
        limits_section = _coerce_mapping(tools_section.get("limits"))
        if limits_section:
            tools = _replace_dataclass(
                tools,
                {
                    "max_tool_tokens": int(limits_section.get("max_tool_tokens", tools.max_tool_tokens)),
                    "max_stdout_bytes": int(limits_section.get("max_stdout_bytes", tools.max_stdout_bytes)),
                    "max_json_fields": int(limits_section.get("max_json_fields", tools.max_json_fields)),
                    "max_lines": int(limits_section.get("max_lines", tools.max_lines)),
                },
            )

    mcp = MCPSettings()
    mcp_section = mapping.get("mcp")
    if isinstance(mcp_section, Mapping):
        servers_value = mcp_section.get("servers", mcp.servers)
        if isinstance(servers_value, (list, tuple)):
            servers: Iterable[str] = tuple(str(item) for item in servers_value if str(item).strip())
        elif isinstance(servers_value, str):
            servers = tuple(part.strip() for part in servers_value.split(",") if part.strip())
        else:
            servers = mcp.servers

        definitions_value = _coerce_sequence(mcp_section.get("definitions"))
        definitions: list[MCPServerDefinition] = []
        if definitions_value:
            for idx, item in enumerate(definitions_value):
                if not isinstance(item, Mapping):
                    raise ValueError("mcp.definitions entries must be tables")
                definitions.append(_parse_mcp_definition(item, base_dir))

        mcp = _replace_dataclass(
            mcp,
            {
                "enable": bool(mcp_section.get("enable", mcp.enable)),
                "servers": tuple(servers) or mcp.servers,
                "definitions": tuple(definitions) or mcp.definitions,
            },
        )

    privacy = PrivacySettings()
    privacy_section = mapping.get("privacy")
    if isinstance(privacy_section, Mapping):
        privacy = _replace_dataclass(
            privacy,
            {
                "no_external_http": bool(
                    privacy_section.get("no_external_http", privacy.no_external_http)
                ),
                "redact_pii": bool(privacy_section.get("redact_pii", privacy.redact_pii)),
            },
        )

    telemetry = TelemetrySettings()
    telemetry_section = mapping.get("telemetry")
    if isinstance(telemetry_section, Mapping):
        export_path_value = telemetry_section.get("export_path")
        export_path: Optional[Path]
        if export_path_value is None or str(export_path_value).strip() == "":
            export_path = None
        else:
            p = Path(str(export_path_value)).expanduser()
            export_path = p.resolve() if p.is_absolute() else (base_dir / p).resolve() if base_dir else p.resolve()

        telemetry = _replace_dataclass(
            telemetry,
            {
                "enable_export": bool(telemetry_section.get("enable_export", telemetry.enable_export)),
                "export_path": export_path,
                "service_name": str(telemetry_section.get("service_name", telemetry.service_name)),
            },
        )

    execution = ExecutionPolicySettings()
    execution_section = mapping.get("execution")
    if isinstance(execution_section, Mapping):
        sandbox = _parse_enum(SandboxPolicy, execution_section.get("sandbox"), execution.sandbox)
        approval = _parse_enum(ApprovalPolicy, execution_section.get("approval"), execution.approval)
        allowed_paths = _coerce_paths(execution_section.get("allowed_paths"), base_dir=base_dir)
        blocked_commands = _coerce_strings(execution_section.get("blocked_commands"))
        timeout_raw = execution_section.get("timeout_seconds")
        if timeout_raw is None:
            timeout = execution.timeout_seconds
        else:
            try:
                timeout = float(timeout_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("execution.timeout_seconds must be numeric") from exc
        execution = ExecutionPolicySettings(
            sandbox=sandbox,
            approval=approval,
            allowed_paths=allowed_paths if allowed_paths is not None else execution.allowed_paths,
            blocked_commands=blocked_commands if blocked_commands is not None else execution.blocked_commands,
            timeout_seconds=timeout,
        )

    return SessionSettings(
        model=model,
        compaction=compaction,
        tools=tools,
        mcp=mcp,
        privacy=privacy,
        execution=execution,
        telemetry=telemetry,
    )


def _coerce_sequence(value: Any) -> Optional[Sequence[Any]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value
    if isinstance(value, str):
        return [value]
    return None


def _parse_mcp_definition(entry: Mapping[str, Any], base_dir: Optional[Path]) -> MCPServerDefinition:
    name_raw = entry.get("name")
    if name_raw is None:
        raise ValueError("mcp definition missing required 'name'")
    name = str(name_raw).strip()
    if not name:
        raise ValueError("mcp definition 'name' must contain text")

    command_raw = entry.get("command")
    if not command_raw:
        raise ValueError(f"mcp definition '{name}' missing required 'command'")
    command = str(command_raw)

    args_value = entry.get("args", ())
    if isinstance(args_value, (list, tuple)):
        args = tuple(str(item) for item in args_value)
    elif isinstance(args_value, str):
        args = tuple(part for part in (segment.strip() for segment in args_value.split() if segment.strip()))
    else:
        raise ValueError(f"mcp definition '{name}' args must be a list or string")

    env = _coerce_env(entry.get("env"))

    cwd_value = entry.get("cwd")
    cwd_path: Optional[Path]
    if cwd_value is not None:
        cwd_path = Path(str(cwd_value)).expanduser()
        if not cwd_path.is_absolute() and base_dir is not None:
            cwd_path = (base_dir / cwd_path).resolve()
        else:
            cwd_path = cwd_path.resolve()
    else:
        cwd_path = None

    encoding = str(entry.get("encoding", "utf-8"))
    encoding_errors = str(entry.get("encoding_errors", "strict"))

    startup_timeout_ms = entry.get("startup_timeout_ms")
    if startup_timeout_ms is not None:
        startup_timeout_ms = int(startup_timeout_ms)

    ttl_value = entry.get("ttl_seconds")
    ttl_seconds: Optional[float]
    if ttl_value is None:
        ttl_seconds = None
    else:
        ttl_seconds = float(ttl_value)
        if ttl_seconds <= 0:
            raise ValueError(f"mcp definition '{name}' ttl_seconds must be positive")

    return MCPServerDefinition(
        name=name,
        command=command,
        args=args,
        env=env,
        cwd=cwd_path,
        encoding=encoding,
        encoding_errors=encoding_errors,
        startup_timeout_ms=startup_timeout_ms,
        ttl_seconds=ttl_seconds,
    )


def _coerce_env(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple((str(k), str(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        pairs: list[tuple[str, str]] = []
        for item in value:
            if isinstance(item, Mapping):
                for key, val in item.items():
                    pairs.append((str(key), str(val)))
            elif isinstance(item, str):
                if "=" not in item:
                    raise ValueError("env entries provided as strings must be KEY=VALUE")
                key, _, val = item.partition("=")
                pairs.append((key.strip(), val.strip()))
            else:
                raise ValueError("env entries must be mappings or KEY=VALUE strings")
        return tuple(pairs)
    raise ValueError("env must be a mapping or sequence of KEY=VALUE strings")

def _parse_enum(enum_cls: type[Enum], raw: Any, default: Enum) -> Enum:
    if raw is None:
        return default
    if isinstance(raw, enum_cls):
        return raw
    if isinstance(raw, str):
        candidate = raw.strip()
        if not candidate:
            return default
        try:
            return enum_cls(candidate.lower())
        except ValueError:
            try:
                return enum_cls[candidate.upper()]
            except KeyError as exc:
                raise ValueError(f"invalid value {raw!r} for {enum_cls.__name__}") from exc
    raise ValueError(f"unsupported value {raw!r} for {enum_cls.__name__}")


def _coerce_paths(value: Any, *, base_dir: Optional[Path]) -> Optional[tuple[Path, ...]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        items = [str(item) for item in value]
    else:
        raise ValueError("allowed_paths must be a string or iterable of strings")
    resolved = []
    for item in items:
        item_str = str(item).strip()
        if not item_str:
            continue
        candidate = Path(item_str).expanduser()
        if not candidate.is_absolute() and base_dir is not None:
            candidate = (base_dir / item_str).expanduser()
        resolved.append(candidate.resolve())
    return tuple(resolved) if resolved else ()


def _coerce_strings(value: Any) -> Optional[tuple[str, ...]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        items = [str(item) for item in value]
    else:
        raise ValueError("blocked_commands must be a string or iterable of strings")
    cleaned = tuple(part.strip() for part in items if str(part).strip())
    return cleaned or ()


def _replace_dataclass(obj: Any, fields: Mapping[str, Any]) -> Any:
    filtered = {k: v for k, v in fields.items() if hasattr(obj, k)}
    return replace(obj, **filtered)


def _coerce_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


def _cast_value(example: Any, raw: Any) -> Any:
    if isinstance(example, Enum):
        if isinstance(raw, Enum):
            return raw
        if isinstance(raw, str):
            candidate = raw.strip()
            if not candidate:
                return example
            try:
                return type(example)(candidate.lower())
            except ValueError:
                try:
                    return type(example)[candidate.upper()]
                except KeyError as exc:
                    raise ValueError(f"invalid enum value {raw!r}") from exc
        raise ValueError(f"unsupported enum raw value {raw!r}")
    if isinstance(example, bool):
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return bool(raw)
    if isinstance(example, int):
        return int(raw)
    if isinstance(example, float):
        return float(raw)
    if isinstance(example, tuple):
        if isinstance(raw, str):
            return tuple(part.strip() for part in raw.split(",") if part.strip())
        if isinstance(raw, Iterable):
            return tuple(str(item) for item in raw)
        return example
    if isinstance(example, list):
        if isinstance(raw, str):
            return [part.strip() for part in raw.split(",") if part.strip()]
        if isinstance(raw, Iterable):
            return [str(item) for item in raw]
        return example
    return type(example)(raw) if type(example) is not type(raw) else raw


__all__ = [
    "SessionSettings",
    "ModelSettings",
    "CompactionSettings",
    "ToolLimitSettings",
    "MCPSettings",
    "MCPServerDefinition",
    "PrivacySettings",
    "ExecutionPolicySettings",
    "load_session_settings",
]
