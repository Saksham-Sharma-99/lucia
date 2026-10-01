from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.db.models import RegistryEntry
from lucia.registry.sync import sync_registry


async def test_list_by_kind_and_connector(authed: AsyncClient) -> None:
    tools = (await authed.get("/api/v1/registry", params={"connector": "slack"})).json()
    assert {t["name"] for t in tools} >= {"slack.send_message", "slack.listen_mention"}
    channels = (await authed.get("/api/v1/registry", params={"kind": "channel"})).json()
    assert {c["name"]: c["channel_tool"] for c in channels}["voice"] == "vapi.place_call"


async def test_connectors_nest_tools_and_setup(authed: AsyncClient) -> None:
    conns = {c["name"]: c for c in (await authed.get("/api/v1/registry/connectors")).json()}
    assert conns["gmail"]["setup"] == "oauth_link"
    assert conns["fax"]["available"] is False
    assert "vapi.place_call" in {t["name"] for t in conns["vapi"]["tools"]}


async def test_sync_marks_removed_entries_unavailable(db: AsyncSession) -> None:
    db.add(RegistryEntry(kind="tool", name="old.tool", display_name="Old", connector="old"))
    await db.commit()
    await sync_registry(db)
    old = await db.scalar(select(RegistryEntry).where(RegistryEntry.name == "old.tool"))
    assert old is not None and old.available is False and old.version == 2
