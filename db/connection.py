"""MongoDB Atlas connection using motor (async driver)."""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

_client: AsyncIOMotorClient | None = None
_db = None

DB_NAME = os.environ.get("MONGODB_DB", "ouroboros")


async def get_database():
    global _client, _db
    if _db is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise ValueError("MONGODB_URI environment variable is required")
        _client = AsyncIOMotorClient(uri)
        _db = _client[DB_NAME]
    return _db


async def close_database():
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
