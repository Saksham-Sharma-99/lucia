from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.api.tags import tag
from lucia.core.config import get_settings
from lucia.db.session import get_session

router = APIRouter(tags=[tag("internal", "health")])

Status = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Status
    postgres: Status
    redis: Status


async def _check_postgres(session: AsyncSession) -> Status:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"


async def _check_redis() -> Status:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    except Exception:
        return "error"
    finally:
        await client.aclose()
    return "ok"


@router.get("/health", summary="Postgres and Redis health", operation_id="getHealth")
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    postgres = await _check_postgres(session)
    redis = await _check_redis()
    overall: Status = "ok" if postgres == "ok" and redis == "ok" else "error"
    return HealthResponse(status=overall, postgres=postgres, redis=redis)
