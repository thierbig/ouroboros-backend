"""OpenAI GPT adapter."""

import json
from typing import AsyncIterator
import openai
from core.adapters.base import LLMAdapter, AgentResponse, ToolCall, TokenUsage


class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key, timeout=120.0)
        self.default_model = "gpt-4o"

    def format_tools(self, tools: list[dict]) -> list[dict]:
        return tools

    def format_messages(self, messages: list[dict]) -> list[dict]:
        return messages

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AgentResponse:
        kwargs = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        response = await self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        content = choice.message.content
        tool_calls = None

        if choice.message.tool_calls:
            tool_calls = []
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments),
                ))

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            ),
            raw=response,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        kwargs = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        stream = await self.client.chat.completions.create(**kwargs)

        tool_calls_building: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices and chunk.usage:
                yield {
                    "type": "usage",
                    "usage": TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                    ),
                }
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                yield {"type": "token", "content": delta.content}

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_building:
                        tool_calls_building[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments": "",
                        }
                    else:
                        if tc_delta.id:
                            tool_calls_building[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            tool_calls_building[idx]["name"] = tc_delta.function.name

                    if tc_delta.function and tc_delta.function.arguments:
                        tool_calls_building[idx]["arguments"] += tc_delta.function.arguments

            if chunk.choices[0].finish_reason:
                for tc_data in tool_calls_building.values():
                    args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                    yield {
                        "type": "tool_call",
                        "tool_call": ToolCall(
                            id=tc_data["id"],
                            name=tc_data["name"],
                            args=args,
                        ),
                    }
