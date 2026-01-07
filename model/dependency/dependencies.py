from model.file_parser import Chromadb_agent
from sqlalchemy.ext.asyncio import AsyncSession
from model.sqlite import AsyncSessionLocal
from functools import lru_cache

##define injection function for sqlite
from typing import AsyncGenerator

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@lru_cache() ##since chromadb is stateless
def get_chromadb_agent_singleton()->Chromadb_agent:
    """chromadb dependency injection"""
    return Chromadb_agent()
    