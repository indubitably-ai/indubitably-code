"""AWS CLI wrapper tool inspired by the AWS API MCP server.

This tool provides a structured interface around the `aws` CLI so that
an agent can invoke AWS service operations using schema-validated input.
It focuses on read-only data retrieval scenarios such as inspecting
CloudWatch Logs when validating Lambda integrations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List


def aws_api_mcp_tool_def() -> dict:
    """Return the JSON schema definition for the AWS API MCP tool."""
    return {
        "name": "aws_api_mcp",
        "description": (
            "Execute read-oriented AWS CLI operations using a structured schema. "
            "Supports selecting the AWS service and operation, optional profile "
            "and region overrides, and passing CLI parameters."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "service": {
                    "type": "string",
                    "description": "AWS service namespace (e.g., logs, lambda, dynamodb).",
                },
                "operation": {
                    "type": "string",
                    "description": "AWS CLI operation name (e.g., describe-log-groups).",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Optional mapping of CLI parameters to values. Keys should match "
                        "the long-form parameter names without the leading dashes."
                    ),
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional raw CLI arguments appended after the structured parameters.",
                },
                "profile": {
                    "type": "string",
                    "description": "Named AWS profile to use for the invocation.",
                },
                "region": {
                    "type": "string",
                    "description": "AWS region override for the command.",
                },
                "output": {
                    "type": "string",
                    "enum": ["json", "yaml", "text", "table"],
                    "description": "Desired AWS CLI output format (defaults to CLI configuration).",
                },
                "expect_json": {
                    "type": "boolean",
                    "description": (
                        "Attempt to pretty-print JSON responses. Defaults to true "
                        "unless another output format is selected."
                    ),
                },
                "disable_pager": {
                    "type": "boolean",
                    "description": "If true, forces --no-cli-pager for the invocation (default true).",
                },
            },
            "required": ["service", "operation"],
        },
    }


def aws_api_mcp_impl(payload: Dict[str, Any]) -> str:
    """Execute an AWS CLI command based on the MCP-style schema input."""
    if not isinstance(payload, dict):
        raise ValueError("Input payload must be an object")

    service = payload.get("service")
    operation = payload.get("operation")
    if not service or not operation:
        raise ValueError("Both 'service' and 'operation' are required")

    cli_path = shutil.which("aws")
    if not cli_path:
        raise RuntimeError(
            "AWS CLI executable not found. Install AWS CLI v2 and ensure 'aws' is on PATH."
        )

    expect_json = payload.get("expect_json")
    output_format = payload.get("output")
    if expect_json is None:
        expect_json = output_format in (None, "json")
    else:
        expect_json = bool(expect_json)

    disable_pager = payload.get("disable_pager")
    if disable_pager is None:
        disable_pager = True

    cmd: List[str] = [cli_path, service, operation]

    profile = payload.get("profile")
    if profile:
        cmd.extend(["--profile", str(profile)])

    region = payload.get("region")
    if region:
        cmd.extend(["--region", str(region)])

    if output_format:
        cmd.extend(["--output", str(output_format)])

    if disable_pager:
        cmd.append("--no-cli-pager")

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
