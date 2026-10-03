"""Run async work from a Celery task: one event loop, engine and LLM client per task invocation,
since asyncpg and HTTP connections can't outlive the loop that opened them."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lucia.core.config import get_settings
from lucia.llm.client import close_llm


def run_async[T](work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def main() -> T:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await work(session)
        finally:
            await engine.dispose()
            await close_llm()

    return asyncio.run(main())
