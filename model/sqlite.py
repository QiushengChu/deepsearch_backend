from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from datetime import datetime

Base = declarative_base()

class SummaryIndex(Base):
    __tablename__ = "summary_index"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return f"<SummaryIndex(session_id='{self.session_id}')>"
    
DATABASE_URL = "sqlite+aiosqlite:///sqlite/app/app_session.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)