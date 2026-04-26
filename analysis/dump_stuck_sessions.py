"""Dump stuck sessions from MongoDB for taxonomy analysis.

Queries sessions matching the stuck definitions from the spec:
1. sessions where error_message is set
2. sessions with chunks having status != "success"/"ok" OR a non-null error
3. sessions where chunk count >= max_iterations and the final chunk has tool_calls
4. sessions where status == "running" but last_activity is >24h old

Plus a broader criterion we added after observing that this DB's sessions are
ALL marked "completed" even when the agent was clearly interrupted mid-loop
(i.e. the chunk stream's last entry still has tool_calls). Without this, the
taxonomy would be near-empty:
5. sessions where the final chunk has tool_calls (session ended mid-loop)

Writes each matching session + its chunks to analysis/dumps/<session_id>.json.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path so we can import db helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId


DUMPS_DIR = Path(__file__).resolve().parent / "dumps"
DUMPS_DIR.mkdir(parents=True, exist_ok=True)

# The websocket handler uses max_iterations=100 (core/agent.py default)
MAX_ITERATIONS = 100


def json_serializer(obj):
    """Handle MongoDB types for JSON serialization."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def get_db():
    uri = os.environ.get("MONGODB_URI")
    db_name = os.environ.get("MONGODB_DB", "ouroboros")
    if not uri:
        raise ValueError("MONGODB_URI not set")
    # Use certifi CA bundle for Python 3.14 + OpenSSL 3.x compatibility with Atlas
    try:
        import certifi
        client = AsyncIOMotorClient(uri, tlsCAFile=certifi.where())
    except ImportError:
        client = AsyncIOMotorClient(uri)
    return client, client[db_name]


async def dump_session(db, session_doc: dict, reason: str):
    """Write session + chunks to a JSON file."""
    sid = str(session_doc["_id"])
    chunks = await db.chunks.find(
        {"session_id": session_doc["_id"]}
    ).sort("chunk_index", 1).to_list(length=5000)

    output = {
        "session": session_doc,
        "chunks": chunks,
        "stuck_reason": reason,
        "dump_time": datetime.now(timezone.utc).isoformat(),
    }

    out_path = DUMPS_DIR / f"{sid}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, default=json_serializer, indent=2)
    return out_path


async def main():
    client, db = await get_db()
    found = {}  # session_id_str -> {session, reason}

    print("=== Category 1: sessions with error_message set ===")
    cat1 = await db.sessions.find(
        {"error_message": {"$exists": True, "$ne": None, "$ne": ""}}
    ).to_list(length=500)
    print(f"  Found {len(cat1)} sessions")
    for s in cat1:
        sid = str(s["_id"])
        if sid not in found:
            found[sid] = {"session": s, "reasons": []}
        found[sid]["reasons"].append("error_message_set")

    print("\n=== Category 2: sessions with chunks having bad status or non-null error ===")
    # Find chunk session_ids where status is not ok/success or error is set
    bad_chunk_pipeline = [
        {"$match": {"$or": [
            {"status": {"$nin": ["ok", "success"]}},
            {"error": {"$ne": None}},
        ]}},
        {"$group": {"_id": "$session_id"}},
    ]
    bad_chunk_sessions = await db.chunks.aggregate(bad_chunk_pipeline).to_list(length=500)
    bad_sids = [r["_id"] for r in bad_chunk_sessions]
    print(f"  Found {len(bad_sids)} sessions with problematic chunks")
    if bad_sids:
        sessions_cat2 = await db.sessions.find(
            {"_id": {"$in": bad_sids}}
        ).to_list(length=500)
        for s in sessions_cat2:
            sid = str(s["_id"])
            if sid not in found:
                found[sid] = {"session": s, "reasons": []}
            found[sid]["reasons"].append("chunk_error_or_bad_status")

    print(f"\n=== Category 3: hit max_iterations wall ===")
    # Sessions with chunk_count >= MAX_ITERATIONS where last chunk has tool_calls
    hit_wall_pipeline = [
        {"$group": {
            "_id": "$session_id",
            "chunk_count": {"$sum": 1},
            "last_chunk_index": {"$max": "$chunk_index"},
        }},
        {"$match": {"chunk_count": {"$gte": MAX_ITERATIONS}}},
    ]
    hit_wall_candidates = await db.chunks.aggregate(hit_wall_pipeline).to_list(length=500)
    print(f"  Found {len(hit_wall_candidates)} sessions with >= {MAX_ITERATIONS} chunks")
    for candidate in hit_wall_candidates:
        # Check if last chunk has tool_calls
        last_chunk = await db.chunks.find_one(
            {"session_id": candidate["_id"], "chunk_index": candidate["last_chunk_index"]}
        )
        if last_chunk and last_chunk.get("tool_calls"):
            sid_obj = candidate["_id"]
            sid = str(sid_obj)
            if sid not in found:
                sess = await db.sessions.find_one({"_id": sid_obj})
                if sess:
                    found[sid] = {"session": sess, "reasons": []}
            if sid in found:
                found[sid]["reasons"].append("hit_max_iterations_wall")

    print(f"\n=== Category 4: abandoned (running but stale > 24h) ===")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cat4 = await db.sessions.find({
        "status": "running",
        "last_activity": {"$lt": cutoff},
    }).to_list(length=500)
    print(f"  Found {len(cat4)} abandoned sessions")
    for s in cat4:
        sid = str(s["_id"])
        if sid not in found:
            found[sid] = {"session": s, "reasons": []}
        found[sid]["reasons"].append("abandoned_running")

    print(f"\n=== Category 5: ended mid-loop (last chunk has tool_calls) ===")
    # This catches sessions marked "completed" that were actually interrupted
    # before the agent emitted a terminal no-tool assistant message. Common
    # signature of WS disconnect, max-iter wall, or silent crash.
    ended_mid = []
    all_sids = set()
    async for s in db.sessions.find({}):
        all_sids.add(str(s["_id"]))
        last_chunk = await db.chunks.find_one(
            {"session_id": s["_id"]}, sort=[("chunk_index", -1)]
        )
        if last_chunk and last_chunk.get("tool_calls"):
            ended_mid.append(s)
    print(f"  Found {len(ended_mid)} sessions ending mid-loop")
    for s in ended_mid:
        sid = str(s["_id"])
        if sid not in found:
            found[sid] = {"session": s, "reasons": []}
        found[sid]["reasons"].append("ended_mid_loop")

    print(f"\n=== Total unique stuck sessions: {len(found)} (of {len(all_sids)} total sessions) ===")

    # Also dump every session not already flagged, tagged "not_stuck", so the
    # taxonomy author has the full corpus available for golden-set selection
    # and to cross-reference apparent anomalies. With only ~20 sessions total
    # this is cheap.
    extra_sids = all_sids - set(found.keys())
    if extra_sids:
        extra_sessions = await db.sessions.find(
            {"_id": {"$in": [ObjectId(s) for s in extra_sids]}}
        ).to_list(length=500)
        for s in extra_sessions:
            found[str(s["_id"])] = {"session": s, "reasons": ["not_stuck"]}

    print(f"\nDumping {len(found)} sessions to {DUMPS_DIR}/ ...")

    for sid, data in found.items():
        reason = ", ".join(data["reasons"])
        path = await dump_session(db, data["session"], reason)
        print(f"  {sid}: {reason} -> {path.name}")

    client.close()

    # Print summary
    reason_counts = {}
    for data in found.values():
        for r in data["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1
    print(f"\n=== Summary ===")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print(f"  Total unique sessions: {len(found)}")


if __name__ == "__main__":
    asyncio.run(main())
