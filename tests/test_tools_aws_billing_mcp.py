import json
from datetime import date
from types import SimpleNamespace

import pytest

import tools_aws_billing_mcp as billing_tool


def test_cli_missing(monkeypatch):
    monkeypatch.setattr(billing_tool.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError) as exc:
        billing_tool.aws_billing_mcp_impl({"operation": "get_cost_and_usage"})

    assert "AWS CLI executable not found" in str(exc.value)


def test_cost_and_usage_timeframe(monkeypatch):
    recorded = {}

    monkeypatch.setattr(billing_tool.shutil, "which", lambda _: "/usr/bin/aws")
    monkeypatch.setattr(billing_tool, "_today", lambda: date(2024, 10, 20))

    def fake_run(cmd, capture_output: bool, text: bool):
        recorded["cmd"] = cmd
        recorded["capture_output"] = capture_output
        recorded["text"] = text
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(billing_tool.subprocess, "run", fake_run)

    result = billing_tool.aws_billing_mcp_impl(
        {
            "operation": "get_cost_and_usage",
            "timeframe": "last_7_days",
            "group_by": ["SERVICE"],
        }
    )

    assert json.loads(result) == {"ok": True}
    cmd = recorded["cmd"]
    assert cmd[:3] == ["/usr/bin/aws", "ce", "get-cost-and-usage"]
    assert "--metrics" in cmd
    time_idx = cmd.index("--time-period") + 1
    assert cmd[time_idx] == "Start=2024-10-14,End=2024-10-21"
    assert "--group-by" in cmd
    group_idx = cmd.index("--group-by") + 1
    assert json.loads(cmd[group_idx]) == [{"Type": "DIMENSION", "Key": "SERVICE"}]
    assert recorded["capture_output"] is True
    assert recorded["text"] is True


def test_dimension_requires_dimension(monkeypatch):
    monkeypatch.setattr(billing_tool.shutil, "which", lambda _: "/usr/bin/aws")

    with pytest.raises(ValueError) as exc:
        billing_tool.aws_billing_mcp_impl({"operation": "get_dimension_values"})

    assert "dimension" in str(exc.value)


def test_usage_forecast_metric(monkeypatch):
    recorded = {}

    monkeypatch.setattr(billing_tool.shutil, "which", lambda _: "/usr/bin/aws")
    monkeypatch.setattr(billing_tool, "_today", lambda: date(2024, 10, 20))

    def fake_run(cmd, capture_output: bool, text: bool):
        recorded["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=json.dumps({"forecast": True}), stderr="")

    monkeypatch.setattr(billing_tool.subprocess, "run", fake_run)

    result = billing_tool.aws_billing_mcp_impl(
        {
            "operation": "get_usage_forecast",
            "timeframe": "last_7_days",
            "granularity": "DAILY",
            "metric": "UsageQuantity",
        }
    )

    assert json.loads(result) == {"forecast": True}
    assert "--metric" in recorded["cmd"]
    metric_idx = recorded["cmd"].index("--metric") + 1
    assert recorded["cmd"][metric_idx] == "UsageQuantity"
