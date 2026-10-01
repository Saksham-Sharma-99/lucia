"""Contract tests: every operation follows the Swagger convention in CLAUDE.md, and the schema
matches the committed snapshot (UPDATE_SNAPSHOTS=1 to accept a deliberate change)."""

import json
import os
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from lucia.api.tags import TAG_DESCRIPTIONS

SNAPSHOT = Path(__file__).parent / "openapi.snapshot.json"


async def _schema(client: AsyncClient) -> dict[str, Any]:
    return (await client.get("/openapi.json")).json()


async def test_every_operation_is_tagged_and_named(client: AsyncClient) -> None:
    ops = [
        (path, method, op)
        for path, item in (await _schema(client))["paths"].items()
        for method, op in item.items()
    ]
    assert ops
    for path, method, op in ops:
        where = f"{method.upper()} {path}"
        assert path.startswith("/api/v1/"), where
        assert len(op.get("tags", [])) == 1, where
        audience, _, _ = op["tags"][0].partition(":")
        assert audience in ("internal", "external") and op["tags"][0] in TAG_DESCRIPTIONS, where
        assert op.get("summary") and op.get("operationId"), where


async def test_openapi_snapshot(client: AsyncClient) -> None:
    schema = await _schema(client)
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    assert schema == json.loads(SNAPSHOT.read_text()), (
        "OpenAPI changed. If deliberate: UPDATE_SNAPSHOTS=1 make test, then make gen-client."
    )
