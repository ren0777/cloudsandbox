import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base
from app import models  # noqa: F401

target_metadata = Base.metadata


def run_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    engine = create_async_engine(get_settings().database_owner_url)
    async with engine.connect() as conn:
        await conn.run_sync(run_sync)
    await engine.dispose()


asyncio.run(run_async())
