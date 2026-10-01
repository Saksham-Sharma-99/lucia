"""The Agents SDK wrapper, against a fake OpenAI Responses API (no network)."""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx2  # openai ships its own httpx fork
import openai
import pytest
from pydantic import BaseModel

from lucia.core.config import get_settings
from lucia.studio.drafter.llm import DrafterError, OpenAIDrafter, get_drafter, openai_drafter

Handler = Callable[[httpx2.Request], Any]


class Out(BaseModel):
    n: int


def _response(text: str, status: str = "completed") -> dict[str, Any]:
    message = {
        "type": "message",
        "id": "msg_1",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6",
        "status": status,
        "output": [message] if text else [],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _stream(*deltas: str, fail: bool = False) -> httpx2.Response:
    events: list[dict[str, Any]] = [
        {"type": "response.created", "response": _response("", "in_progress")},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "message",
                "id": "msg_1",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
        *(
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": d,
                "logprobs": [],
            }
            for d in deltas
        ),
        {"type": "error", "code": "server_error", "message": "boom", "param": None}
        if fail
        else {"type": "response.completed", "response": _response("".join(deltas))},
    ]
    body = "".join(
        f"event: {e['type']}\ndata: {json.dumps({**e, 'sequence_number': i})}\n\n"
        for i, e in enumerate(events)
    )
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _drafter(handler: Handler, requests: list[httpx2.Request] | None = None) -> OpenAIDrafter:
    async def record(req: httpx2.Request) -> httpx2.Response:
        if requests is not None:
            requests.append(req)
        resp = handler(req)
        return await resp if asyncio.iscoroutine(resp) else resp

    http = openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(record))
    client = openai.AsyncOpenAI(api_key="sk-test", http_client=http, max_retries=0)
    return OpenAIDrafter("gpt-5.6", client)


async def test_structured_output_is_strict_and_not_stored() -> None:
    requests: list[httpx2.Request] = []
    drafter = _drafter(lambda _: httpx2.Response(200, json=_response('{"n": 3}')), requests)
    assert await drafter.run_structured("Be brief.", "{}", Out, 5) == Out(n=3)
    body = json.loads(requests[0].content)
    assert body["store"] is False
    assert body["model"] == "gpt-5.6"
    assert body["instructions"] == "Be brief."
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["required"] == ["n"]


async def test_stream_yields_only_text_deltas() -> None:
    requests: list[httpx2.Request] = []
    drafter = _drafter(lambda _: _stream("## Role\n", "You chase."), requests)
    assert [d async for d in drafter.stream_text("i", "{}", 5)] == ["## Role\n", "You chase."]
    body = json.loads(requests[0].content)
    assert body["stream"] is True and body["store"] is False


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(
            401, json={"error": {"message": "bad key", "type": "invalid_request_error"}}
        ),
        httpx2.Response(500, json={"error": {"message": "boom", "type": "server_error"}}),
        httpx2.Response(200, json=_response("not json")),  # model broke the schema
        httpx2.Response(200, json=_response('{"n": "three"}')),
    ],
    ids=["unauthorized", "server_error", "invalid_json", "wrong_shape"],
)
async def test_provider_failures_are_502(response: httpx2.Response) -> None:
    with pytest.raises(DrafterError) as err:
        await _drafter(lambda _: response).run_structured("i", "{}", Out, 5)
    assert (err.value.problem.status, err.value.code) == (502, "provider_error")


async def test_stream_failure_is_502() -> None:
    drafter = _drafter(lambda _: httpx2.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(DrafterError) as err:
        _ = [d async for d in drafter.stream_text("i", "{}", 5)]
    assert err.value.code == "provider_error"


async def _slow(_: httpx2.Request) -> httpx2.Response:
    await asyncio.sleep(1)
    return httpx2.Response(200, json=_response('{"n": 1}'))


async def test_slow_calls_time_out_as_504() -> None:
    with pytest.raises(DrafterError) as err:
        await _drafter(_slow).run_structured("i", "{}", Out, 0.05)
    assert (err.value.problem.status, err.value.code) == (504, "timeout")
    with pytest.raises(DrafterError) as err:
        _ = [d async for d in _drafter(_slow).stream_text("i", "{}", 0.05)]
    assert err.value.code == "timeout"


def test_no_key_means_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    with pytest.raises(DrafterError) as err:
        get_drafter()
    assert (err.value.problem.status, err.value.code) == (503, "not_configured")


def test_one_drafter_per_model_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    try:
        assert get_drafter() is get_drafter()
    finally:
        openai_drafter.cache_clear()


async def test_a_stream_that_fails_after_some_text_is_502() -> None:
    drafter = _drafter(lambda _: _stream("## Role\n", fail=True))
    got: list[str] = []
    with pytest.raises(DrafterError) as err:
        async for delta in drafter.stream_text("i", "{}", 5):
            got.append(delta)
    assert got == ["## Role\n"]
    assert err.value.code == "provider_error"


async def test_a_consumer_can_stop_early() -> None:
    stream = _drafter(lambda _: _stream("a", "b", "c")).stream_text("i", "{}", 5)
    assert await anext(stream) == "a"
    await stream.aclose()  # e.g. the browser went away


@pytest.mark.parametrize("call", ["structured", "stream"])
async def test_prompt_text_never_reaches_the_logs(
    call: str, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "Jane Doe DOB 1980-01-01"
    caplog.set_level(logging.DEBUG)
    if call == "structured":
        drafter = _drafter(
            lambda _: httpx2.Response(200, json=_response(f'{{"n": {len(secret)}}}'))
        )
        await drafter.run_structured(f"About {secret}", secret, Out, 5)
    else:
        drafter = _drafter(lambda _: _stream(secret))
        _ = [d async for d in drafter.stream_text(f"About {secret}", secret, 5)]
    assert caplog.records
    assert not [r for r in caplog.records if secret in r.getMessage()]
