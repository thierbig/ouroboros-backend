"""Regression tests for the mid-tool-call termination bug.

Targets the three fixes from analysis/fixes/termination.md:

1. Tool dispatch runs on a worker thread so the asyncio event loop can
   continue processing WS pings during long subprocess calls.
2. WebSocket disconnects label sessions as status="disconnected", not
   indistinguishably-"completed".
3. tool_msg is appended to history BEFORE the tool_result event is
   yielded, so the persisted messages array always matches what the
   frontend has received.

Each test is written to fail on `main @ c23dc73` and pass after the fix.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from core.adapters.base import AgentResponse, ToolCall, TokenUsage
from core.agent import Agent
from core.registry import ToolRegistry


def _text_response(content: str) -> AgentResponse:
    return AgentResponse(
        content=content,
        tool_calls=None,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        raw={},
    )


def _tool_response(calls: list[tuple[str, dict]]) -> AgentResponse:
    return AgentResponse(
        content=None,
        tool_calls=[ToolCall(id=f"tc_{i}", name=n, args=a) for i, (n, a) in enumerate(calls)],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        raw={},
    )


class TestEventLoopUnblocked:
    @pytest.mark.asyncio
    async def test_blocking_tool_does_not_freeze_event_loop(self):
        """A synchronously-blocking tool handler must not freeze the event loop.

        Before the fix, registry.dispatch ran on the event loop thread, so
        a blocking subprocess call (terminal, pyth_deploy) would starve
        uvicorn's WS ping task and manifest at ~40 s as a silent
        WebSocketDisconnect. See session_termination_cause.md §4.2.
        """
        reg = ToolRegistry()

        BLOCK_SECONDS = 0.5

        def blocking_handler(args):
            # Equivalent to proc.wait(timeout=180) in tools/terminal.py
            time.sleep(BLOCK_SECONDS)
            return "done"

        reg.register("blocker", {
            "name": "blocker",
            "description": "Blocks",
            "parameters": {"type": "object", "properties": {}},
        }, blocking_handler)

        adapter = AsyncMock()
        adapter.chat.side_effect = [
            _tool_response([("blocker", {})]),
            _text_response("ok"),
        ]

        # Parallel ticker every 50 ms. With dispatch on the event-loop
        # thread, we'd expect ~0 ticks during the 500 ms block. With
        # asyncio.to_thread we expect ~10 ticks.
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        agent = Agent(adapter=adapter, registry=reg, max_iterations=5)
        tick_task = asyncio.create_task(ticker())
        try:
            async for _ in agent.run("go", []):
                pass
        finally:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass

        # 5 ticks is a conservative floor; a healthy loop ticks 8-10×.
        assert ticks >= 5, (
            f"Event loop appears blocked during tool dispatch "
            f"(only {ticks} ticks in {BLOCK_SECONDS}s window)"
        )


class TestDisconnectLabeling:
    @pytest.mark.asyncio
    async def test_mark_disconnected_writes_disconnected_status(self):
        """mark_disconnected must set status='disconnected' on a running session.

        Simulates the except WebSocketDisconnect branch at
        api/websocket.py:194. Pre-fix that branch wrote status='completed'
        indistinguishably from a clean finish.
        """
        from db import models

        recorded = {}

        class FakeCollection:
            async def update_one(self, filt, update):
                recorded["filter"] = filt
                recorded["update"] = update

        class FakeDB:
            sessions = FakeCollection()

        async def fake_get_database():
            return FakeDB()

        session_id = ObjectId()
        with patch.object(models, "get_database", fake_get_database):
            await models.mark_disconnected(session_id, total_tokens=42, total_cost=0.01)

        assert recorded["update"]["$set"]["status"] == "disconnected"
        assert recorded["update"]["$set"]["total_tokens"] == 42
        assert recorded["update"]["$set"]["total_cost"] == 0.01
        # Filter must require status='running' so clean completions aren't overwritten.
        assert recorded["filter"].get("status") == "running"
        assert recorded["filter"]["_id"] == session_id

    @pytest.mark.asyncio
    async def test_mark_disconnected_does_not_overwrite_completed(self):
        """A second mark_disconnected after a clean completion must be a no-op.

        Matches the outer-loop branch in api/websocket.py: if the inner
        handler already wrote status='completed', the outer client-close
        shouldn't rewrite it. The running-only filter enforces that.
        """
        from db import models

        recorded_filter = {}

        class FakeCollection:
            async def update_one(self, filt, update):
                recorded_filter.update(filt)

        class FakeDB:
            sessions = FakeCollection()

        async def fake_get_database():
            return FakeDB()

        with patch.object(models, "get_database", fake_get_database):
            await models.mark_disconnected(ObjectId())

        # We don't verify matched_count here because the fake returns None;
        # the contract test is that the filter *includes* status='running'
        # so Mongo itself skips non-running docs.
        assert recorded_filter.get("status") == "running"


class TestSaveSkewFixed:
    @pytest.mark.asyncio
    async def test_tool_msg_appended_before_tool_result_yield(self):
        """When tool_result is yielded, the corresponding tool_msg must
        already be present in history.

        Pre-fix, `yield tool_result` happened BEFORE `history.append(tool_msg)`,
        so a WS save triggered by the tool_result event wrote a history
        that ended on 'assistant' and was permanently one tool message
        behind. Shape-A sessions in session_termination_cause.md §1 all
        exhibit this signature.
        """
        reg = ToolRegistry()
        reg.register("echo", {
            "name": "echo",
            "description": "Echoes input",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }, lambda args: args.get("text", ""))

        adapter = AsyncMock()
        adapter.chat.side_effect = [
            _tool_response([("echo", {"text": "first"})]),
            _text_response("done"),
        ]

        agent = Agent(adapter=adapter, registry=reg, max_iterations=5)
        history: list[dict] = []

        # Snapshot history the moment the first tool_result is yielded.
        snapshot = None
        async for event in agent.run("go", history):
            if event["type"] == "tool_result" and snapshot is None:
                snapshot = [dict(m) for m in history]

        assert snapshot is not None, "tool_result event was never yielded"

        tool_msgs = [m for m in snapshot if m.get("role") == "tool"]
        assert len(tool_msgs) == 1, (
            f"Expected tool_msg in history at tool_result yield time, "
            f"got roles: {[m.get('role') for m in snapshot]}"
        )
        assert tool_msgs[0]["content"] == "first"
        assert tool_msgs[0]["tool_call_id"] == "tc_0"
