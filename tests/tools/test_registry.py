import asyncio

import pytest

from tools.handler import ToolHandler, ToolInvocation, ToolKind, ToolOutput
from tools.payload import FunctionToolPayload, ToolPayload
from tools.registry import ConfiguredToolSpec, ToolRegistry, ToolRegistryBuilder
from tools.spec import ToolSpec


class _EchoHandler:
    def __init__(self) -> None:
        self.kind = ToolKind.FUNCTION
        self.invocations: list[ToolInvocation] = []

    def matches_kind(self, payload: ToolPayload) -> bool:
        return isinstance(payload, FunctionToolPayload)

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        self.invocations.append(invocation)
        text = invocation.payload.arguments.get("text", "")  # type: ignore[attr-defined]
        return ToolOutput(content=text.upper(), success=True)


def test_registry_dispatches_to_registered_handler():
    handler = _EchoHandler()
    registry = ToolRegistry({"echo": handler})
    payload = ToolPayload.function({"text": "hi"})
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name="echo",
        payload=payload,
    )

    output = asyncio.run(registry.dispatch(invocation))
    assert output.success is True
    assert output.content == "HI"
    assert handler.invocations and handler.invocations[0] is invocation


def test_registry_handles_missing_handler():
    registry = ToolRegistry({})
    payload = ToolPayload.function({})
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name="missing",
        payload=payload,
    )

    output = asyncio.run(registry.dispatch(invocation))
    assert output.success is False
    assert "not found" in output.content


def test_registry_rejects_incompatible_payload():
    handler = _EchoHandler()
    registry = ToolRegistry({"echo": handler})
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name="echo",
        payload=ToolPayload.custom("custom", {}),
    )

    output = asyncio.run(registry.dispatch(invocation))
    assert output.success is False
    assert "incompatible" in output.content


def test_registry_builder_collects_specs_and_handlers():
    builder = ToolRegistryBuilder()
    handler = _EchoHandler()
    spec = ToolSpec(name="echo", description="Echo text", input_schema={})
    builder.register_handler("echo", handler)
    builder.add_spec(spec, supports_parallel=True)

    specs, registry = builder.build()
    assert specs == [ConfiguredToolSpec(spec, True)]

    payload = ToolPayload.function({"text": "ok"})
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name="echo",
        payload=payload,
    )

    output = asyncio.run(registry.dispatch(invocation))
    assert output.success is True
    assert output.content == "OK"
