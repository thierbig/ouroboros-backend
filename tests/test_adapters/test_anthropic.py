# tests/test_adapters/test_anthropic.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import AgentResponse, ToolCall, TokenUsage


@pytest.fixture
def adapter():
    return AnthropicAdapter(api_key="test-key")


class TestAnthropicAdapter:
    @pytest.mark.asyncio
    async def test_chat_text_response(self, adapter):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Hello from Claude")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 25
        mock_response.stop_reason = "end_turn"

        with patch.object(adapter.client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
            result = await adapter.chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-sonnet-4-20250514",
            )

        assert isinstance(result, AgentResponse)
        assert result.content == "Hello from Claude"
        assert result.tool_calls is None
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 25

    @pytest.mark.asyncio
    async def test_chat_tool_call_response(self, adapter):
        mock_tool_block = MagicMock(type="tool_use")
        mock_tool_block.id = "toolu_123"
        mock_tool_block.name = "read_file"
        mock_tool_block.input = {"path": "test.py"}

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "tool_use"

        with patch.object(adapter.client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
            result = await adapter.chat(
                messages=[{"role": "user", "content": "Read test.py"}],
                tools=[{"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": {}}}],
                model="claude-sonnet-4-20250514",
            )

        assert result.has_tool_calls
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].args == {"path": "test.py"}
        assert result.tool_calls[0].id == "toolu_123"

    @pytest.mark.asyncio
    async def test_chat_mixed_content(self, adapter):
        mock_text = MagicMock(type="text", text="Let me read that file.")
        mock_tool = MagicMock(type="tool_use")
        mock_tool.id = "toolu_456"
        mock_tool.name = "read_file"
        mock_tool.input = {"path": "main.py"}

        mock_response = MagicMock()
        mock_response.content = [mock_text, mock_tool]
        mock_response.usage.input_tokens = 150
        mock_response.usage.output_tokens = 40
        mock_response.stop_reason = "tool_use"

        with patch.object(adapter.client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
            result = await adapter.chat(
                messages=[{"role": "user", "content": "Read main.py"}],
                tools=[{"type": "function", "function": {"name": "read_file", "description": "Read", "parameters": {}}}],
                model="claude-sonnet-4-20250514",
            )

        assert result.content == "Let me read that file."
        assert result.has_tool_calls
        assert result.tool_calls[0].name == "read_file"

    def test_format_tools_converts_openai_to_anthropic(self, adapter):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]
        anthropic_tools = adapter.format_tools(openai_tools)
        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["name"] == "read_file"
        assert anthropic_tools[0]["description"] == "Read a file"
        assert "input_schema" in anthropic_tools[0]

    def test_format_messages_for_anthropic(self, adapter):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        system, api_messages = adapter.format_messages(messages)
        assert system == "You are helpful."
        assert len(api_messages) == 2
        assert api_messages[0]["role"] == "user"
        assert api_messages[1]["role"] == "assistant"
