"""Anthropic Claude adapter."""

import json
from typing import AsyncIterator
import anthropic
from core.adapters.base import LLMAdapter, AgentResponse, ToolCall, TokenUsage


class AnthropicAdapter(LLMAdapter):
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=120.0,  # 2 min timeout per API call
        )
        self.default_model = "claude-sonnet-4-20250514"

    def format_tools(self, openai_tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tool schemas to Anthropic format."""
        anthropic_tools = []
        for tool in openai_tools:
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def format_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Extract system prompt and format messages for Anthropic API.
        Returns (system_prompt, api_messages).

        Handles merging consecutive tool results into a single user message
        and removing orphaned tool_use blocks that lack matching tool_results.
        """
        system = ""
        api_messages: list[dict] = []

        # Collect all tool_call_ids that have results
        tool_result_ids = {
            msg["tool_call_id"]
            for msg in messages
            if msg["role"] == "tool" and "tool_call_id" in msg
        }

        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            elif msg["role"] == "tool":
                # Merge into previous user message if it already has tool_results
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg["content"],
                }
                if (
                    api_messages
                    and api_messages[-1]["role"] == "user"
                    and isinstance(api_messages[-1]["content"], list)
                    and api_messages[-1]["content"]
                    and api_messages[-1]["content"][0].get("type") == "tool_result"
                ):
                    api_messages[-1]["content"].append(tool_result_block)
                else:
                    api_messages.append({
                        "role": "user",
                        "content": [tool_result_block],
                    })
            elif msg["role"] == "assistant" and "tool_calls" in msg:
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                # Only include tool_use blocks that have matching tool_results
                for tc in msg["tool_calls"]:
                    if tc["id"] in tool_result_ids:
                        content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"])
                            if isinstance(tc["function"]["arguments"], str)
                            else tc["function"]["arguments"],
                        })
                if content:
                    api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

        return system, api_messages

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AgentResponse:
        system, api_messages = self.format_messages(messages)

        kwargs = {
            "model": model or self.default_model,
            "max_tokens": 8192,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        response = await self.client.messages.create(**kwargs)

        content = None
        tool_calls = None

        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    args=block.input,
                ))

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
            ),
            raw=response,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        system, api_messages = self.format_messages(messages)

        kwargs = {
            "model": model or self.default_model,
            "max_tokens": 8192,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self.format_tools(tools)

        async with self.client.messages.stream(**kwargs) as stream:
            current_tool_id = None
            current_tool_name = None
            current_tool_json = ""

            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool_id = event.content_block.id
                        current_tool_name = event.content_block.name
                        current_tool_json = ""

                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "token", "content": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        current_tool_json += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_name:
                        args = json.loads(current_tool_json) if current_tool_json else {}
                        yield {
                            "type": "tool_call",
                            "tool_call": ToolCall(
                                id=current_tool_id,
                                name=current_tool_name,
                                args=args,
                            ),
                        }
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_json = ""

            final = await stream.get_final_message()
            yield {
                "type": "usage",
                "usage": TokenUsage(
                    prompt_tokens=final.usage.input_tokens,
                    completion_tokens=final.usage.output_tokens,
                ),
            }
