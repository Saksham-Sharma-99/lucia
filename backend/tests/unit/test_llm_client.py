"""The runtime LLM client against a fake OpenAI Responses API (no network)."""

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx2  # openai ships its own httpx fork
import openai
import pytest
from pydantic import BaseModel

from lucia.llm.client import LLMError, OpenAILLM
from lucia.llm.fake import FakeLLM


class Out(BaseModel):
    n: int


USAGE = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "total_tokens": 1500,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 0},
}


def _response(output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6",
        "status": "completed",
        "output": output,
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": USAGE,
    }


def _text(text: str) -> dict[str, Any]:
    return _response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ]
    )


def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return _response(
        [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": name,
                "arguments": json.dumps(args),
                "status": "completed",
            }
        ]
    )


def _llm(handler: Any, requests: list[httpx2.Request] | None = None) -> OpenAILLM:
    async def record(req: httpx2.Request) -> httpx2.Response:
        if requests is not None:
            requests.append(req)
        resp = handler(req)
        return await resp if asyncio.iscoroutine(resp) else resp

    http = openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(record))
    return OpenAILLM(openai.AsyncOpenAI(api_key="sk-test", http_client=http, max_retries=0))


async def test_structured_returns_output_and_usage_with_cost() -> None:
    requests: list[httpx2.Request] = []
    llm = _llm(lambda _: httpx2.Response(200, json=_text('{"n": 3}')), requests)
    out, usage = await llm.structured(
        role="planner", model="gpt-5.6", instructions="i", message="m", output_type=Out
    )
    assert out == Out(n=3)
    assert (usage.model, usage.input_tokens, usage.output_tokens) == ("gpt-5.6", 1000, 500)
    assert usage.cost > Decimal(0)
    assert json.loads(requests[0].content)["store"] is False


async def test_text_returns_the_message() -> None:
    text, _ = await _llm(lambda _: httpx2.Response(200, json=_text("hello"))).text(
        role="summarizer", model="gpt-5.6-luna", instructions="i", message="m"
    )
    assert text == "hello"


async def test_tool_call_forces_the_tool_and_returns_its_arguments() -> None:
    requests: list[httpx2.Request] = []
    llm = _llm(
        lambda _: httpx2.Response(200, json=_tool_call("vapi__place_call", {"a": 1})), requests
    )
    args, _ = await llm.tool_call(
        role="executor",
        model="gpt-5.6-sol",
        instructions="i",
        message="m",
        tool_name="vapi.place_call",
        tool_schema={"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
    )
    assert args == {"a": 1}
    body = json.loads(requests[0].content)
    assert body["tool_choice"] == {"type": "function", "name": "vapi__place_call"}
    assert body["parallel_tool_calls"] is False


async def test_timeout_is_retryable() -> None:
    async def slow(_: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(1)
        return httpx2.Response(200, json=_text('{"n": 1}'))

    with pytest.raises(LLMError) as err:
        await _llm(slow).structured(
            role="x", model="gpt-5.6", instructions="i", message="m", output_type=Out, seconds=0.05
        )
    assert err.value.retryable is True


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx2.Response(500, json={"error": {"message": "boom", "type": "server_error"}}), True),
        (
            httpx2.Response(400, json={"error": {"message": "bad", "type": "invalid_request"}}),
            False,
        ),
        (httpx2.Response(200, json=_text("not json")), False),
    ],
    ids=["server_error", "bad_request", "invalid_output"],
)
async def test_provider_errors_map_to_llm_error(response: httpx2.Response, retryable: bool) -> None:
    with pytest.raises(LLMError) as err:
        await _llm(lambda _: response).structured(
            role="x", model="gpt-5.6", instructions="i", message="m", output_type=Out
        )
    assert err.value.retryable is retryable


async def test_fake_llm_replays_scripted_outputs_per_role() -> None:
    fake = FakeLLM()
    fake.on("planner", Out(n=1), Out(n=2))
    fake.on("executor", {"to": "x"})
    first, _ = await fake.structured(
        role="planner", model="m", instructions="i", message="a", output_type=Out
    )
    second, _ = await fake.structured(
        role="planner", model="m", instructions="i", message="b", output_type=Out
    )
    args, _ = await fake.tool_call(
        role="executor", model="m", instructions="i", message="c", tool_name="t", tool_schema={}
    )
    assert (first.n, second.n, args) == (1, 2, {"to": "x"})
    assert [r for r, _ in fake.calls] == ["planner", "planner", "executor"]
    with pytest.raises(AssertionError, match="no scripted output for role planner"):
        await fake.structured(
            role="planner", model="m", instructions="i", message="d", output_type=Out
        )


async def test_fake_llm_raises_scripted_errors() -> None:
    fake = FakeLLM()
    fake.on("brief", LLMError("down", retryable=True))
    with pytest.raises(LLMError):
        await fake.text(role="brief", model="m", instructions="i", message="m")
