# tests/test_agent.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.agent import Agent
from core.adapters.base import AgentResponse, ToolCall, TokenUsage
from core.registry import ToolRegistry


def make_text_response(text: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> AgentResponse:
    return AgentResponse(
        content=text,
        tool_calls=None,
        usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        raw={},
    )


def make_tool_response(calls: list[tuple[str, dict]], prompt_tokens: int = 100, completion_tokens: int = 50) -> AgentResponse:
    tool_calls = [ToolCall(id=f"tc_{i}", name=name, args=args) for i, (name, args) in enumerate(calls)]
    return AgentResponse(
        content=None,
        tool_calls=tool_calls,
        usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        raw={},
    )


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register("echo", {
        "name": "echo",
        "description": "Echo input",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
    }, lambda args: args.get("text", ""))
    return reg


@pytest.fixture
def mock_adapter():
    adapter = AsyncMock()
    return adapter


class TestAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, mock_adapter, registry):
        """Agent yields response event when LLM returns text with no tool calls."""
        mock_adapter.chat.return_value = make_text_response("Hello!")

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=10)
        events = []
        async for event in agent.run("Hi", []):
            events.append(event)

        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1
        assert response_events[0]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_tool_call_and_result(self, mock_adapter, registry):
        """Agent executes tool calls and feeds results back."""
        mock_adapter.chat.side_effect = [
            make_tool_response([("echo", {"text": "test"})]),
            make_text_response("Done!"),
        ]

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=10)
        events = []
        async for event in agent.run("Echo test", []):
            events.append(event)

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "response" in types

        tool_call_event = next(e for e in events if e["type"] == "tool_call")
        assert tool_call_event["name"] == "echo"

        tool_result_event = next(e for e in events if e["type"] == "tool_result")
        assert tool_result_event["result"] == "test"

    @pytest.mark.asyncio
    async def test_max_iterations_forces_summary(self, mock_adapter, registry):
        """When max iterations hit, agent forces a summary response."""
        mock_adapter.chat.side_effect = [
            make_tool_response([("echo", {"text": "loop"})]),
            make_tool_response([("echo", {"text": "loop"})]),
            make_tool_response([("echo", {"text": "loop"})]),
            make_text_response("Forced summary"),  # summary call
        ]

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=3)
        events = []
        async for event in agent.run("Loop forever", []):
            events.append(event)

        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1

    @pytest.mark.asyncio
    async def test_budget_warning_injected(self, mock_adapter, registry):
        """Budget warning is injected when approaching max iterations."""
        mock_adapter.chat.side_effect = [
            make_tool_response([("echo", {"text": "1"})]),
            make_tool_response([("echo", {"text": "2"})]),
            make_tool_response([("echo", {"text": "3"})]),
            make_tool_response([("echo", {"text": "4"})]),
            make_tool_response([("echo", {"text": "5"})]),
            make_tool_response([("echo", {"text": "6"})]),
            make_tool_response([("echo", {"text": "7"})]),
            make_tool_response([("echo", {"text": "8"})]),
            make_text_response("Done"),  # forced summary
        ]

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=10)
        events = []
        async for event in agent.run("Go", []):
            events.append(event)

        # Check that a budget warning was injected in one of the later calls
        calls = mock_adapter.chat.call_args_list
        later_calls_messages = [str(call) for call in calls[7:]]
        budget_mentioned = any("budget" in s.lower() or "iteration" in s.lower() for s in later_calls_messages)
        assert budget_mentioned

    @pytest.mark.asyncio
    async def test_interrupt_stops_loop(self, mock_adapter, registry):
        """Setting interrupt flag stops the agent loop."""
        call_count = 0

        async def chat_with_interrupt(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                agent.interrupt()
            return make_tool_response([("echo", {"text": "again"})])

        mock_adapter.chat.side_effect = chat_with_interrupt

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=100)
        events = []
        async for event in agent.run("Go", []):
            events.append(event)

        assert call_count <= 3

    @pytest.mark.asyncio
    async def test_tool_result_truncation(self, mock_adapter, registry):
        """Tool results over 100K chars are truncated."""
        big_output = "x" * 150_000
        reg = ToolRegistry()
        reg.register("big", {
            "name": "big",
            "description": "Returns big output",
            "parameters": {"type": "object", "properties": {}},
        }, lambda args: big_output)

        mock_adapter.chat.side_effect = [
            make_tool_response([("big", {})]),
            make_text_response("Done"),
        ]

        agent = Agent(adapter=mock_adapter, registry=reg, max_iterations=10)
        events = []
        async for event in agent.run("Run big", []):
            events.append(event)

        tool_result_event = next(e for e in events if e["type"] == "tool_result")
        assert len(tool_result_event["result"]) < 150_000
        assert "truncated" in tool_result_event["result"].lower()

    @pytest.mark.asyncio
    async def test_usage_events_emitted(self, mock_adapter, registry):
        """Usage events are emitted after each LLM call."""
        mock_adapter.chat.return_value = make_text_response("Hi", prompt_tokens=200, completion_tokens=100)

        agent = Agent(adapter=mock_adapter, registry=registry, max_iterations=10)
        events = []
        async for event in agent.run("Hi", []):
            events.append(event)

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) >= 1
        assert usage_events[0]["tokens_used"] > 0

    @pytest.mark.asyncio
    async def test_auto_error_recovery(self, mock_adapter, registry):
        """When terminal returns stderr, auto-feed it back with self_correcting event."""
        reg = ToolRegistry()
        reg.register("terminal", {
            "name": "terminal",
            "description": "Run command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        }, lambda args: json.dumps({"output": "", "stderr": "ModuleNotFoundError: No module named 'flask'", "exit_code": 1, "error": None}))

        mock_adapter.chat.side_effect = [
            make_tool_response([("terminal", {"command": "python app.py"})]),
            make_text_response("I see the error, let me fix it."),
        ]

        agent = Agent(adapter=mock_adapter, registry=reg, max_iterations=10)
        events = []
        async for event in agent.run("Run the app", []):
            events.append(event)

        types = [e["type"] for e in events]
        assert "self_correcting" in types
