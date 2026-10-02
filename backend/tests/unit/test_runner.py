import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lucia.core.config import get_settings
from lucia.llm.client import OpenAILLM, get_llm
from lucia.worker.runner import run_async


def test_a_task_closes_its_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")

    async def work(_: AsyncSession) -> OpenAILLM:
        llm = get_llm()
        assert isinstance(llm, OpenAILLM)
        return llm

    first, second = run_async(work), run_async(work)
    assert first is not second
    assert first.client.is_closed() and second.client.is_closed()
