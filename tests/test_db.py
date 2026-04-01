# tests/test_db.py
import pytest
import asyncio
from datetime import datetime, timezone
from db.connection import get_database, close_database
from db.models import create_session, get_session, update_session_status, list_sessions, add_chunk, get_chunks_for_session, get_stats


@pytest.fixture
async def db():
    """Get test database, clean up after."""
    database = await get_database()
    yield database
    await database.sessions.delete_many({"_test": True})
    await database.chunks.delete_many({"_test": True})
    await close_database()


class TestMongoDB:
    @pytest.mark.asyncio
    async def test_create_session(self, db):
        session_id = await create_session(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            working_dir="/test/dir",
            _test=True,
        )
        assert session_id is not None

        session = await get_session(session_id)
        assert session is not None
        assert session["provider"] == "anthropic"
        assert session["model"] == "claude-sonnet-4-20250514"
        assert session["status"] == "running"
        assert session["total_tokens"] == 0
        assert session["total_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_update_session_status(self, db):
        session_id = await create_session(
            provider="openai",
            model="gpt-4o",
            _test=True,
        )
        await update_session_status(session_id, "completed", total_tokens=1500, total_cost=0.05)

        session = await get_session(session_id)
        assert session["status"] == "completed"
        assert session["total_tokens"] == 1500
        assert session["total_cost"] == 0.05

    @pytest.mark.asyncio
    async def test_list_sessions(self, db):
        s1 = await create_session(provider="anthropic", model="claude-sonnet-4-20250514", _test=True)
        s2 = await create_session(provider="openai", model="gpt-4o", _test=True)

        sessions = await list_sessions()
        ids = [str(s["_id"]) for s in sessions]
        assert str(s1) in ids
        assert str(s2) in ids

    @pytest.mark.asyncio
    async def test_add_and_get_chunks(self, db):
        session_id = await create_session(provider="anthropic", model="claude-sonnet-4-20250514", _test=True)

        await add_chunk(
            session_id=session_id,
            chunk_index=1,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            prompt=[{"role": "user", "content": "Hi"}],
            response={"content": "Hello!"},
            prompt_tokens=100,
            response_tokens=50,
            cost=0.001,
            latency_ms=500,
            tool_calls=[],
            status="ok",
            _test=True,
        )
        await add_chunk(
            session_id=session_id,
            chunk_index=2,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            prompt=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}],
            response={"content": "How can I help?"},
            prompt_tokens=200,
            response_tokens=75,
            cost=0.002,
            latency_ms=600,
            tool_calls=[{"name": "read_file", "args": {"path": "test.py"}}],
            status="ok",
            _test=True,
        )

        chunks = await get_chunks_for_session(session_id)
        assert len(chunks) == 2
        assert chunks[0]["chunk_index"] == 1
        assert chunks[1]["chunk_index"] == 2
        assert chunks[1]["tool_calls"][0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_get_stats(self, db):
        s1 = await create_session(provider="anthropic", model="claude-sonnet-4-20250514", _test=True)
        await update_session_status(s1, "completed", total_tokens=1000, total_cost=0.03)
        s2 = await create_session(provider="openai", model="gpt-4o", _test=True)
        await update_session_status(s2, "completed", total_tokens=500, total_cost=0.01)

        stats = await get_stats()
        assert stats["total_tokens"] >= 1500
        assert stats["total_cost"] >= 0.04
