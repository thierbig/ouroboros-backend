"""MongoDB session and chunk operations."""

import json
from datetime import datetime, timezone
from bson import ObjectId
from db.connection import get_database


async def create_session(
    provider: str,
    model: str,
    working_dir: str | None = None,
    **extra,
) -> ObjectId:
    db = await get_database()
    now = datetime.now(timezone.utc)
    doc = {
        "created_at": now,
        "last_activity": now,
        "status": "running",
        "provider": provider,
        "model": model,
        "working_dir": working_dir,
        "total_tokens": 0,
        "total_cost": 0.0,
        "messages": [],
        **extra,
    }
    result = await db.sessions.insert_one(doc)
    return result.inserted_id


async def get_session(session_id: ObjectId | str) -> dict | None:
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)
    return await db.sessions.find_one({"_id": session_id})


async def update_session_status(
    session_id: ObjectId | str,
    status: str,
    total_tokens: int = 0,
    total_cost: float = 0.0,
    error_message: str | None = None,
) -> None:
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)
    update: dict = {
        "status": status,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
    }
    if error_message:
        update["error_message"] = error_message
    await db.sessions.update_one(
        {"_id": session_id},
        {"$set": update},
    )


async def update_session_messages(session_id: ObjectId | str, messages: list[dict]) -> None:
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)
    await db.sessions.update_one(
        {"_id": session_id},
        {"$set": {"messages": messages, "last_activity": datetime.now(timezone.utc)}},
    )


async def list_sessions_for_project(working_dir: str) -> list[dict]:
    """List all sessions for a given working directory, most recent first."""
    db = await get_database()
    cursor = db.sessions.find(
        {"working_dir": working_dir, "hidden": {"$ne": True}},
    ).sort("created_at", -1)
    return await cursor.to_list(length=50)


async def hide_session(session_id: ObjectId | str) -> None:
    """Soft-delete a session (hide from users, keep for stats)."""
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)
    await db.sessions.update_one(
        {"_id": session_id},
        {"$set": {"hidden": True}},
    )


async def get_latest_session_for_project(working_dir: str) -> dict | None:
    """Get the most recent session for a given working directory."""
    db = await get_database()
    return await db.sessions.find_one(
        {"working_dir": working_dir, "hidden": {"$ne": True}},
        sort=[("created_at", -1)],
    )


async def list_sessions() -> list[dict]:
    db = await get_database()
    cursor = db.sessions.find().sort("created_at", -1)
    return await cursor.to_list(length=100)


async def add_chunk(
    session_id: ObjectId | str,
    chunk_index: int,
    provider: str,
    model: str,
    prompt: list[dict],
    response: dict,
    prompt_tokens: int,
    response_tokens: int,
    cost: float,
    latency_ms: int,
    tool_calls: list[dict],
    status: str,
    error: str | None = None,
    **extra,
) -> ObjectId:
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)

    prompt_json = json.dumps(prompt, default=str)
    response_json = json.dumps(response, default=str)

    doc = {
        "session_id": session_id,
        "chunk_index": chunk_index,
        "created_at": datetime.now(timezone.utc),
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "prompt_tokens": prompt_tokens,
        "prompt_size_kb": round(len(prompt_json) / 1024, 2),
        "response": response,
        "response_tokens": response_tokens,
        "response_size_kb": round(len(response_json) / 1024, 2),
        "total_tokens": prompt_tokens + response_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "status": status,
        "error": error,
        **extra,
    }
    result = await db.chunks.insert_one(doc)
    # Update session last_activity
    await db.sessions.update_one(
        {"_id": session_id},
        {"$set": {"last_activity": datetime.now(timezone.utc)}},
    )
    return result.inserted_id


async def get_chunks_for_session(session_id: ObjectId | str) -> list[dict]:
    db = await get_database()
    if isinstance(session_id, str):
        session_id = ObjectId(session_id)
    cursor = db.chunks.find({"session_id": session_id}).sort("chunk_index", 1)
    return await cursor.to_list(length=1000)


async def get_stats() -> dict:
    db = await get_database()
    pipeline = [
        {"$group": {
            "_id": None,
            "total_tokens": {"$sum": "$total_tokens"},
            "total_cost": {"$sum": "$total_cost"},
            "session_count": {"$sum": 1},
        }},
    ]
    result = await db.sessions.aggregate(pipeline).to_list(length=1)
    if result:
        return {
            "total_tokens": result[0]["total_tokens"],
            "total_cost": result[0]["total_cost"],
            "session_count": result[0]["session_count"],
        }
    return {"total_tokens": 0, "total_cost": 0.0, "session_count": 0}
