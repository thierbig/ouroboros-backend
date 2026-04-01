"""End-to-end test: runs a full agent conversation with mocked LLM."""

import asyncio
import json
import sys
import os

sys.path.insert(0, ".")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from unittest.mock import AsyncMock
from core.agent import Agent
from core.tools import create_tool_registry
from core.adapters.base import AgentResponse, ToolCall, TokenUsage


async def main():
    registry = create_tool_registry()
    print(f"[OK] Registry loaded with {len(registry.get_tool_names())} tools: {registry.get_tool_names()}")

    # Mock adapter that simulates: read_file -> terminal -> final response
    adapter = AsyncMock()
    call_count = 0

    def mock_chat(messages, tools=None):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return AgentResponse(
                content="Let me read the file first.",
                tool_calls=[ToolCall(id="tc_1", name="read_file", args={"path": "scripts/test_e2e.py"})],
                usage=TokenUsage(prompt_tokens=500, completion_tokens=100),
                raw={},
            )
        elif call_count == 2:
            return AgentResponse(
                content=None,
                tool_calls=[ToolCall(id="tc_2", name="terminal", args={"command": "echo 'hello from ouroboros'"})],
                usage=TokenUsage(prompt_tokens=800, completion_tokens=150),
                raw={},
            )
        else:
            return AgentResponse(
                content="I read the test script and ran a command. Everything works!",
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=1000, completion_tokens=200),
                raw={},
            )

    adapter.chat.side_effect = mock_chat

    agent = Agent(adapter=adapter, registry=registry, max_iterations=10, working_dir=".")
    print("\n--- Running agent conversation ---\n")

    async for event in agent.run("Test the agent", []):
        if event["type"] == "tool_call":
            print(f"  [TOOL] {event['name']}({json.dumps(event['args'])})")
        elif event["type"] == "tool_result":
            preview = event["result"][:100] + "..." if len(event["result"]) > 100 else event["result"]
            print(f"  [RESULT] {preview}")
        elif event["type"] == "response":
            print(f"  [RESPONSE] {event['content']}")
        elif event["type"] == "usage":
            print(f"  [USAGE] Tokens: {event['tokens_used']} (iteration {event['iteration']}/{event['max_iterations']})")
        elif event["type"] == "self_correcting":
            print(f"  [SELF-CORRECTING] {event['error']}")

    print("\n[OK] End-to-end test passed!")


if __name__ == "__main__":
    asyncio.run(main())
