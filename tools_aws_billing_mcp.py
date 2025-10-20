"""AWS Billing & Cost Management MCP-style tool.

This tool exposes a high-level interface to AWS Cost Explorer operations via the
`aws ce` CLI. It mirrors the intent of the AWS Billing Cost Management MCP server
so agents can request cost insights in natural language. The implementation keeps
common parameters ergonomic (time ranges, metrics, grouping) while still allowing
advanced overrides through raw parameters or extra arguments.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


_OPERATION_MAP = {
    "get_cost_and_usage": "get-cost-and-usage",
    "get_cost_and_usage_with_resources": "get-cost-and-usage-with-resources",
    "get_cost_forecast": "get-cost-forecast",
    "get_usage_forecast": "get-usage-forecast",
    "get_dimension_values": "get-dimension-values",
    "get_cost_categories": "get-cost-categories",
}


_VALID_TIMEFRAMES = {
    "today",
    "yesterday",
    "last_7_days",
    "last_14_days",
    "last_30_days",
    "month_to_date",
    "this_month",
    "last_month",
}


def aws_billing_mcp_tool_def() -> dict:
    return {
        "name": "aws_billing_mcp",
        "description": (
            "Retrieve AWS Cost Explorer analytics through a guided schema that mirrors the Billing MCP server. Specify the Cost Explorer `operation` "
            "(for example, get_cost_and_usage or get_usage_forecast) and choose either a friendly `timeframe` helper (last_7_days, month_to_date, etc.) or an explicit "
            "`time_period` with ISO dates; the helper expands into appropriate start/end values. You can fine-tune grouping with `group_by`, target particular metrics via `metrics`/`metric`, "
            "add raw CLI filters or sort blocks, and page through responses with `next_page_token`. The tool constructs the underlying `aws ce ...` command, enforces sane defaults such as `--no-cli-pager`, "
            "and pretty-prints JSON output so downstream agents can reason about the result structure. Example: to analyze unblended cost by service over the previous month call with operation='get_cost_and_usage', "
            "timeframe='last_month', metrics=['UnblendedCost'], group_by=[{'type': 'DIMENSION', 'key': 'SERVICE'}]. Limitations: the host must have AWS CLI credentials with Cost Explorer access, only one operation is executed per call, and the tool is read-only—do not rely on it for cost allocation tag mutations or budgeting setup."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": sorted(_OPERATION_MAP.keys()),
                    "description": "Cost Explorer operation to invoke.",
                },
                "timeframe": {
                    "type": "string",
                    "enum": sorted(_VALID_TIMEFRAMES),
                    "description": "Convenience time range selector (e.g., last_7_days).",
                },
                "time_period": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "Inclusive start date YYYY-MM-DD."},
                        "end": {"type": "string", "description": "Exclusive end date YYYY-MM-DD."},
                    },
                    "required": ["start", "end"],
                    "additionalProperties": False,
                    "description": "Explicit AWS Cost Explorer time period overrides timeframe.",
                },
                "granularity": {
                    "type": "string",
                    "enum": ["DAILY", "MONTHLY", "HOURLY"],
                    "description": "Cost Explorer granularity (defaults depend on operation).",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Metric names for cost & usage queries (e.g., UnblendedCost).",
                },
                "metric": {
                    "type": "string",
                    "description": "Single metric override for forecast operations.",
                },
                "group_by": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "key": {"type": "string"},
                                },
                                "required": ["type", "key"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "description": "Group results by dimensions or tags.",
                },
                "dimension": {
                    "type": "string",
                    "description": "Dimension name required by get_dimension_values (e.g., SERVICE).",
                },
                "filter": {
                    "type": "object",
                    "description": "Raw Cost Explorer filter expression (JSON structure).",
                },
                "sort_by": {
                    "type": "object",
                    "description": "Sort directive for cost queries (JSON structure).",
                },
                "next_page_token": {
                    "type": "string",
                    "description": "Resume pagination from a previous response token.",
                },
                "profile": {
                    "type": "string",
                    "description": "AWS CLI profile name to use for credentials.",
                },
                "region": {
                    "type": "string",
                    "description": "Region override (Cost Explorer is us-east-1 by default).",
                },
                "output": {
                    "type": "string",
                    "enum": ["json", "yaml", "text", "table"],
                    "description": "AWS CLI output format (defaults to json for this tool).",
                },
                "expect_json": {
                    "type": "boolean",
                    "description": "Pretty-print JSON responses (default true).",
                },
                "disable_pager": {
                    "type": "boolean",
                    "description": "Force --no-cli-pager (default true).",
                },
                "parameters": {
                    "type": "object",
                    "description": "Advanced parameters passed directly to the CLI (key/value).",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional CLI arguments appended verbatim.",
                },
            },
            "required": ["operation"],
        },
    }


def aws_billing_mcp_impl(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Input payload must be an object")

    cli_path = shutil.which("aws")
    if not cli_path:
        raise RuntimeError(
            "AWS CLI executable not found. Install AWS CLI v2 and ensure 'aws' is on PATH."
        )

    operation_key = payload.get("operation")
    if not operation_key:
        raise ValueError("'operation' is required")

    cli_operation = _OPERATION_MAP.get(operation_key)
    if not cli_operation:
        raise ValueError(
            f"Unsupported operation '{operation_key}'. Allowed: {', '.join(sorted(_OPERATION_MAP))}"
        )

    expect_json = payload.get("expect_json")
    output_format = payload.get("output") or "json"
    if expect_json is None:
        expect_json = output_format in (None, "json")
    else:
        expect_json = bool(expect_json)

    disable_pager = payload.get("disable_pager")
    if disable_pager is None:
        disable_pager = True

    cmd: List[str] = [cli_path, "ce", cli_operation]

    profile = payload.get("profile")
    if profile:
        cmd.extend(["--profile", str(profile)])

    region = payload.get("region") or "us-east-1"
    cmd.extend(["--region", str(region)])

    if output_format:
        cmd.extend(["--output", str(output_format)])

    if disable_pager:
        cmd.append("--no-cli-pager")

    time_period = _resolve_time_period(payload)
    if time_period is not None:
        cmd.extend(["--time-period", f"Start={time_period[0]},End={time_period[1]}"])

    granularity = payload.get("granularity")
    if granularity:
        cmd.extend(["--granularity", granularity.upper()])

    metrics = _resolve_metrics(payload, operation_key)
    if metrics:
        if cli_operation in {"get-cost-and-usage", "get-cost-and-usage-with-resources"}:
            cmd.append("--metrics")
            cmd.extend(metrics)
        elif cli_operation in {"get-cost-forecast", "get-usage-forecast"}:
            cmd.extend(["--metric", metrics[0]])

    group_by = payload.get("group_by")
    if group_by and cli_operation in {"get-cost-and-usage", "get-cost-and-usage-with-resources"}:
        cmd.extend(["--group-by", json.dumps(_format_group_by(group_by), ensure_ascii=False)])

    filter_obj = payload.get("filter")
    if filter_obj is not None:
        if not isinstance(filter_obj, dict):
            raise ValueError("'filter' must be an object")
        cmd.extend(["--filter", json.dumps(filter_obj, ensure_ascii=False)])

    sort_by = payload.get("sort_by")
    if sort_by is not None:
        if not isinstance(sort_by, dict):
            raise ValueError("'sort_by' must be an object")
        cmd.extend(["--sort-by", json.dumps(sort_by, ensure_ascii=False)])

    next_token = payload.get("next_page_token")
    if next_token:
        cmd.extend(["--next-page-token", str(next_token)])

    dimension = payload.get("dimension")
    if cli_operation == "get-dimension-values":
        if not dimension:
            raise ValueError("'dimension' is required for get_dimension_values")
        cmd.extend(["--dimension", str(dimension)])

    parameters = payload.get("parameters")
    if parameters is not None:
        cmd.extend(_serialize_parameters(parameters))

    extra_args = payload.get("extra_args")
    if extra_args is not None:
        if not isinstance(extra_args, list) or not all(isinstance(arg, str) for arg in extra_args):
            raise ValueError("'extra_args' must be a list of strings")
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        diagnostic = stderr or stdout or "no CLI output"
        raise RuntimeError(f"AWS CLI command failed ({result.returncode}): {diagnostic}")

    output = result.stdout.strip() or result.stderr.strip()
    if not output:
        return "<no output>"

    if expect_json:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            pass
        else:
            return json.dumps(parsed, ensure_ascii=False, indent=2)

    return output


def _resolve_time_period(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    if "time_period" in payload and payload["time_period"] is not None:
        raw = payload["time_period"]
        if not isinstance(raw, dict):
            raise ValueError("'time_period' must be an object with start/end")
        start = raw.get("start")
        end = raw.get("end")
        if not start or not end:
            raise ValueError("'time_period' requires both start and end dates")
        return start, end

    timeframe = payload.get("timeframe")
    if not timeframe:
        return None
    if timeframe not in _VALID_TIMEFRAMES:
        raise ValueError(
            f"Invalid timeframe '{timeframe}'. Allowed: {', '.join(sorted(_VALID_TIMEFRAMES))}"
        )

    today = _today()
    if timeframe == "today":
        start = today
        end = today + timedelta(days=1)
    elif timeframe == "yesterday":
        end = today
        start = end - timedelta(days=1)
    elif timeframe == "last_7_days":
        end = today + timedelta(days=1)
        start = end - timedelta(days=7)
    elif timeframe == "last_14_days":
        end = today + timedelta(days=1)
        start = end - timedelta(days=14)
    elif timeframe == "last_30_days":
        end = today + timedelta(days=1)
        start = end - timedelta(days=30)
    elif timeframe in {"this_month", "month_to_date"}:
        start = today.replace(day=1)
        end = today + timedelta(days=1)
    elif timeframe == "last_month":
        first_this_month = today.replace(day=1)
        end = first_this_month
        start = (first_this_month - timedelta(days=1)).replace(day=1)
    else:
        raise ValueError(f"Unhandled timeframe '{timeframe}'")

    return start.isoformat(), end.isoformat()


def _resolve_metrics(payload: Dict[str, Any], operation_key: str) -> List[str]:
    metrics = payload.get("metrics")
    metric = payload.get("metric")

    if metrics is not None and not isinstance(metrics, list):
        raise ValueError("'metrics' must be a list of strings")

    if metrics:
        if not all(isinstance(item, str) for item in metrics):
            raise ValueError("All items in 'metrics' must be strings")
    if metric is not None and not isinstance(metric, str):
        raise ValueError("'metric' must be a string")

    if operation_key in {"get_cost_forecast", "get_usage_forecast"}:
        if metric:
            return [metric]
        if metrics:
            return [metrics[0]]
        return ["UnblendedCost" if operation_key == "get_cost_forecast" else "UsageQuantity"]

    if metrics:
        return metrics

    return ["UnblendedCost"]


def _format_group_by(group_by: List[Any]) -> List[Dict[str, Any]]:
    formatted: List[Dict[str, Any]] = []
    for entry in group_by:
        if isinstance(entry, str):
            formatted.append({"Type": "DIMENSION", "Key": entry.upper()})
        elif isinstance(entry, dict):
            type_val = entry.get("type") or entry.get("Type")
            key_val = entry.get("key") or entry.get("Key")
            if not type_val or not key_val:
                raise ValueError("Group-by objects require 'type' and 'key'")
            formatted.append({"Type": type_val.upper(), "Key": key_val})
        else:
            raise ValueError("group_by entries must be strings or objects with type/key")
    return formatted


def _serialize_parameters(parameters: Any) -> List[str]:
    if not isinstance(parameters, dict):
        raise ValueError("'parameters' must be an object mapping parameter names to values")

    args: List[str] = []
    for key, value in parameters.items():
        if value is None:
            continue
        if not isinstance(key, str) or not key:
            raise ValueError("Parameter names must be non-empty strings")
        flag = f"--{key}" if not key.startswith("-") else key
        args.extend(_format_parameter(flag, value))
    return args


def _format_parameter(flag: str, value: Any) -> List[str]:
    if isinstance(value, bool):
        return [flag, "true" if value else "false"]
    if isinstance(value, (int, float)):
        return [flag, str(value)]
    if isinstance(value, str):
        return [flag, value]
    if isinstance(value, (list, dict)):
        return [flag, json.dumps(value, ensure_ascii=False)]
    raise ValueError(f"Unsupported parameter type for {flag}: {type(value).__name__}")


def _today() -> date:
    return date.today()
