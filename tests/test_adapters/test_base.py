# tests/test_adapters/test_base.py
import pytest
from core.adapters.base import AgentResponse, ToolCall, TokenUsage


class TestAgentResponse:
    def test_text_response(self):
        resp = AgentResponse(
            content="Hello world",
            tool_calls=None,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            raw={},
        )
        assert resp.content == "Hello world"
        assert resp.tool_calls is None
        assert resp.usage.total_tokens == 15
        assert not resp.has_tool_calls

    def test_tool_call_response(self):
        calls = [
            ToolCall(id="tc_1", name="read_file", args={"path": "test.py"}),
            ToolCall(id="tc_2", name="terminal", args={"command": "ls"}),
        ]
        resp = AgentResponse(
            content=None,
            tool_calls=calls,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50),
            raw={},
        )
        assert resp.has_tool_calls
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "read_file"

    def test_token_usage(self):
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500)
        assert usage.total_tokens == 1500
