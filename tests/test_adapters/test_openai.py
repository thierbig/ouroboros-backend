# tests/test_adapters/test_openai.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.adapters.openai import OpenAIAdapter
from core.adapters.base import AgentResponse, ToolCall, TokenUsage


@pytest.fixture
def adapter():
    return OpenAIAdapter(api_key="test-key")


class TestOpenAIAdapter:
    @pytest.mark.asyncio
    async def test_chat_text_response(self, adapter):
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from GPT"
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 25

        with patch.object(adapter.client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_response):
            result = await adapter.chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="gpt-4o",
            )

        assert isinstance(result, AgentResponse)
        assert result.content == "Hello from GPT"
        assert result.tool_calls is None
        assert result.usage.prompt_tokens == 100

    @pytest.mark.asyncio
    async def test_chat_tool_call_response(self, adapter):
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "read_file"
        mock_tool_call.function.arguments = '{"path": "test.py"}'

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tool_call]
        mock_choice.finish_reason = "tool_calls"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 200
        mock_response.usage.completion_tokens = 50

        with patch.object(adapter.client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_response):
            result = await adapter.chat(
                messages=[{"role": "user", "content": "Read test.py"}],
                tools=[{"type": "function", "function": {"name": "read_file", "description": "Read", "parameters": {}}}],
                model="gpt-4o",
            )

        assert result.has_tool_calls
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].args == {"path": "test.py"}

    def test_format_messages_passes_through(self, adapter):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = adapter.format_messages(messages)
        assert result == messages

    def test_tools_already_in_openai_format(self, adapter):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = adapter.format_tools(tools)
        assert result == tools
