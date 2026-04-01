"""Test the full server stack — MongoDB, FastAPI, routes."""

import asyncio
import sys
sys.path.insert(0, ".")

from db.connection import get_database, close_database
from db.models import list_sessions, get_stats


async def main():
    print("[1] Testing MongoDB connection...")
    db = await get_database()
    collections = await db.list_collection_names()
    print(f"    Connected! Collections: {collections}")

    print("[2] Testing session listing...")
    sessions = await list_sessions()
    print(f"    Found {len(sessions)} sessions")

    print("[3] Testing stats...")
    stats = await get_stats()
    print(f"    Stats: {stats}")

    print("[4] Testing FastAPI import...")
    from api.main import app
    print(f"    App: {app.title}")
    routes = [r.path for r in app.routes]
    print(f"    Routes: {routes}")

    await close_database()
    print("\n[OK] All checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
