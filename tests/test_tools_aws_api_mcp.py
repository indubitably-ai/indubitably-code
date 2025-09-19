import json
from types import SimpleNamespace

import pytest

import tools_aws_api_mcp as aws_tool


def test_cli_missing(monkeypatch):
    monkeypatch.setattr(aws_tool.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError) as exc:
        aws_tool.aws_api_mcp_impl({"service": "logs", "operation": "describe-log-groups"})

    assert "AWS CLI executable not found" in str(exc.value)


def test_successful_invocation(monkeypatch):
    recorded = {}

    def fake_which(binary: str) -> str:
        assert binary == "aws"
        return "/usr/bin/aws"

    def fake_run(cmd, capture_output: bool, text: bool):
        recorded["cmd"] = cmd
        recorded["capture_output"] = capture_output
        recorded["text"] = text
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(aws_tool.shutil, "which", fake_which)
    monkeypatch.setattr(aws_tool.subprocess, "run", fake_run)

    payload = {
        "service": "logs",
        "operation": "filter-log-events",
        "profile": "dev",
        "region": "us-west-2",
        "parameters": {
            "log-group-name": "/aws/lambda/sample",
            "limit": 20,
        },
        "extra_args": ["--start-time", "1700000000"],
    }

    result = aws_tool.aws_api_mcp_impl(payload)

    assert json.loads(result) == {"ok": True}
    assert recorded["cmd"] == [
        "/usr/bin/aws",
        "logs",
        "filter-log-events",
        "--profile",
        "dev",
        "--region",
        "us-west-2",
        "--no-cli-pager",
        "--log-group-name",
        "/aws/lambda/sample",
        "--limit",
        "20",
        "--start-time",
        "1700000000",
    ]
    assert recorded["capture_output"] is True
    assert recorded["text"] is True


def test_invalid_extra_args(monkeypatch):
    monkeypatch.setattr(aws_tool.shutil, "which", lambda _: "/usr/bin/aws")

    with pytest.raises(ValueError):
        aws_tool.aws_api_mcp_impl(
            {
                "service": "logs",
                "operation": "describe-log-streams",
                "extra_args": "not-a-list",
            }
        )
