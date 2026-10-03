"""Live chat events over Redis pub/sub, relayed to the browser as SSE (CHANNELS_SPEC §3.2)."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi.sse import ServerSentEvent
from redis.asyncio import Redis

from lucia.core.config import get_settings


def _channel(conversation_id: uuid.UUID) -> str:
    return f"conv:{conversation_id}"


async def publish(conversation_id: uuid.UUID, event: str, data: dict[str, Any]) -> None:
    """A fresh client per call: workers publish from their own short-lived event loops."""
    async with Redis.from_url(get_settings().redis_url, decode_responses=True) as redis:
        await redis.publish(
            _channel(conversation_id), json.dumps({"event": event, "data": data}, default=str)
        )


async def stream(
    conversation_id: uuid.UUID, *, limit: int | None = None
) -> AsyncIterator[ServerSentEvent]:
    async with Redis.from_url(get_settings().redis_url, decode_responses=True) as redis:
        pubsub = redis.pubsub()
        await pubsub.subscribe(_channel(conversation_id))
        try:
            sent = 0
            async for raw in pubsub.listen():
                if raw["type"] != "message":
                    continue
                payload = json.loads(raw["data"])
                yield ServerSentEvent(event=payload["event"], data=payload["data"])
                sent += 1
                if limit is not None and sent >= limit:
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
