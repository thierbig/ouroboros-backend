"""WebSocket endpoint for agent conversations."""

import json
import time
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.agent import Agent
from core.tools import create_tool_registry
from core.adapters.anthropic import AnthropicAdapter
from core.adapters.openai import OpenAIAdapter
from core.pricing import calculate_cost
from db.models import create_session, update_session_status, update_session_messages, add_chunk
from tools.terminal import set_stream_callback

router = APIRouter()


async def _heartbeat(ws: WebSocket, interval: int = 10):
    """Send periodic heartbeat while waiting for LLM response."""
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await ws.send_json({"type": "heartbeat"})
            except Exception:
                break
    except asyncio.CancelledError:
        pass


def get_adapter(provider: str, api_key: str):
    if provider == "anthropic":
        return AnthropicAdapter(api_key=api_key)
    elif provider == "openai":
        return OpenAIAdapter(api_key=api_key)
    else:
        raise ValueError(f"Unknown provider: {provider}")


@router.websocket("/agent")
async def agent_websocket(ws: WebSocket):
    await ws.accept()

    registry = create_tool_registry()
    agent: Agent | None = None
    session_id = None
    chunk_index = 0
    total_tokens = 0
    total_cost = 0.0
    messages_history: list[dict] = []

    # Queue for streaming terminal output from sync thread to async ws
    terminal_queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_terminal_line(line: str):
        """Called from terminal thread — pushes line to async queue."""
        loop.call_soon_threadsafe(terminal_queue.put_nowait, line)

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if data["type"] == "stop":
                if agent:
                    agent.interrupt()
                continue

            if data["type"] == "resume":
                # Restore a previous session's history
                resume_id = data.get("session_id")
                if resume_id:
                    from db.models import get_session
                    prev = await get_session(resume_id)
                    if prev and prev.get("messages"):
                        messages_history.clear()
                        messages_history.extend(prev["messages"])
                        session_id = prev["_id"]
                        total_tokens = prev.get("total_tokens", 0)
                        total_cost = prev.get("total_cost", 0.0)
                        await ws.send_json({"type": "session", "session_id": str(session_id)})
                        await ws.send_json({"type": "resumed", "message_count": len(messages_history)})
                continue

            if data["type"] == "message":
                config = data.get("config", {})
                provider = config.get("provider", "anthropic")
                model = config.get("model", "claude-sonnet-4-20250514")
                api_key = config.get("api_key", "")
                working_dir = config.get("working_dir")

                if not api_key:
                    await ws.send_json({"type": "error", "message": "API key is required"})
                    continue

                adapter = get_adapter(provider, api_key)
                agent = Agent(
                    adapter=adapter,
                    registry=registry,
                    max_iterations=100,
                    working_dir=working_dir,
                )

                if session_id is None:
                    session_id = await create_session(
                        provider=provider,
                        model=model,
                        working_dir=working_dir,
                    )
                    await ws.send_json({"type": "session", "session_id": str(session_id)})

                user_content = data["content"]

                original_chat = adapter.chat

                async def chat_with_logging(msgs, tools=None):
                    nonlocal chunk_index, total_tokens, total_cost
                    chunk_index += 1
                    start_time = time.time()

                    # Heartbeat while waiting for LLM response
                    heartbeat_task = asyncio.create_task(_heartbeat(ws))
                    try:
                        response = await original_chat(msgs, tools)
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass

                    latency_ms = int((time.time() - start_time) * 1000)
                    cost = calculate_cost(provider, model, response.usage.prompt_tokens, response.usage.completion_tokens)
                    total_tokens += response.usage.total_tokens
                    total_cost += cost

                    logged_tool_calls = []
                    if response.tool_calls:
                        logged_tool_calls = [{"name": tc.name, "args": tc.args} for tc in response.tool_calls]

                    await add_chunk(
                        session_id=session_id,
                        chunk_index=chunk_index,
                        provider=provider,
                        model=model,
                        prompt=msgs,
                        response={"content": response.content, "tool_calls": logged_tool_calls},
                        prompt_tokens=response.usage.prompt_tokens,
                        response_tokens=response.usage.completion_tokens,
                        cost=cost,
                        latency_ms=latency_ms,
                        tool_calls=logged_tool_calls,
                        status="ok",
                    )

                    return response

                adapter.chat = chat_with_logging

                # Install terminal streaming callback
                set_stream_callback(on_terminal_line)

                try:
                    last_save_len = len(messages_history)
                    async for event in agent.run(user_content, messages_history):
                        # Before sending the event, flush any queued terminal output
                        while not terminal_queue.empty():
                            try:
                                line = terminal_queue.get_nowait()
                                await ws.send_json({"type": "terminal_output", "line": line})
                            except asyncio.QueueEmpty:
                                break

                        await ws.send_json(event)

                        # Incremental save: persist after each tool result
                        if event.get("type") == "tool_result" and len(messages_history) > last_save_len:
                            await update_session_messages(session_id, messages_history)
                            last_save_len = len(messages_history)

                    # Flush remaining terminal output
                    while not terminal_queue.empty():
                        try:
                            line = terminal_queue.get_nowait()
                            await ws.send_json({"type": "terminal_output", "line": line})
                        except asyncio.QueueEmpty:
                            break

                    await update_session_messages(session_id, messages_history)
                    await update_session_status(session_id, "completed", total_tokens=total_tokens, total_cost=total_cost)
                    await ws.send_json({"type": "done"})

                except WebSocketDisconnect:
                    # Client left mid-stream — save what we have and exit cleanly
                    if session_id:
                        await update_session_messages(session_id, messages_history)
                        await update_session_status(session_id, "completed", total_tokens=total_tokens, total_cost=total_cost)
                    raise  # Re-raise to break the outer while loop
                except Exception as e:
                    try:
                        await ws.send_json({"type": "error", "message": str(e)})
                    except Exception:
                        pass
                    if session_id:
                        await update_session_messages(session_id, messages_history)
                        await update_session_status(session_id, "error", total_tokens=total_tokens, total_cost=total_cost, error_message=str(e))
                finally:
                    set_stream_callback(None)

    except WebSocketDisconnect:
        if session_id:
            await update_session_messages(session_id, messages_history)
            await update_session_status(session_id, "completed", total_tokens=total_tokens, total_cost=total_cost)
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        if session_id:
            await update_session_messages(session_id, messages_history)
            await update_session_status(session_id, "error", total_tokens=total_tokens, total_cost=total_cost, error_message=str(e))
    finally:
        set_stream_callback(None)
