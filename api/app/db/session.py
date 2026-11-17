"""Async SQLAlchemy engine and session factory (PostgreSQL 16 + asyncpg)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine, timeout_seconds: float) -> None:
    """Readiness probe: one ``SELECT 1`` within the timeout. Raises on failure."""
    async with asyncio.timeout(timeout_seconds), engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
