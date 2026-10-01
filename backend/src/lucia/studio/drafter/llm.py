"""One-shot model calls through the OpenAI Agents SDK: no tools, one turn, nothing stored.

Requests set `store=False` and tracing is off, so prompts never leave the call (contracts §7.2).
`get_drafter` is the FastAPI dependency; tests swap in a fake.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Protocol

import openai
from agents import Agent, AgentsException, ModelSettings, OpenAIResponsesModel, Runner
from agents.run import RunConfig
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel

from lucia.core.config import get_settings
from lucia.core.errors import ProblemError

_RUN = RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)
_SETTINGS = ModelSettings(store=False)

log = logging.getLogger(__name__)


class DrafterError(ProblemError):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(status, "Drafting failed", detail, type_=f"urn:lucia:drafter:{code}")
        self.code = code


@asynccontextmanager
async def _guard(deadline: float) -> AsyncIterator[None]:
    """Fails the call at `deadline` (loop time); SDK and provider errors become DrafterErrors.
    Never held across a `yield` to the caller, so a timeout can't fire in the caller's code."""
    try:
        async with asyncio.timeout_at(deadline):
            yield
    except (TimeoutError, openai.APITimeoutError) as e:
        log.warning("drafter call timed out")
        raise DrafterError(504, "timeout", "The drafter took too long. Try again.") from e
    except (AgentsException, openai.OpenAIError) as e:
        log.warning("drafter call failed: %s", type(e).__name__)
        raise DrafterError(502, "provider_error", "The model provider failed. Try again.") from e


def _deadline(seconds: float) -> float:
    return asyncio.get_running_loop().time() + seconds


class Drafter(Protocol):
    def stream_text(
        self, instructions: str, message: str, seconds: float
    ) -> AsyncIterator[str]: ...

    async def run_structured[T: BaseModel](
        self, instructions: str, message: str, output_type: type[T], seconds: float
    ) -> T: ...


class OpenAIDrafter:
    def __init__(self, model: str, client: openai.AsyncOpenAI) -> None:
        self._model = OpenAIResponsesModel(model, client)

    def _agent(self, instructions: str, output_type: type[BaseModel] | None = None) -> Agent[None]:
        return Agent(
            name="drafter",
            instructions=instructions,
            model=self._model,
            model_settings=_SETTINGS,
            output_type=output_type,
        )

    async def stream_text(
        self, instructions: str, message: str, seconds: float
    ) -> AsyncGenerator[str]:
        deadline = _deadline(seconds)
        result = Runner.run_streamed(
            self._agent(instructions), message, max_turns=1, run_config=_RUN
        )
        events = result.stream_events()
        try:
            while True:
                async with _guard(deadline):
                    event = await anext(events, None)
                if event is None:
                    return
                if event.type == "raw_response_event" and isinstance(
                    event.data, ResponseTextDeltaEvent
                ):
                    yield event.data.delta
        finally:
            result.cancel()

    async def run_structured[T: BaseModel](
        self, instructions: str, message: str, output_type: type[T], seconds: float
    ) -> T:
        async with _guard(_deadline(seconds)):
            result = await Runner.run(
                self._agent(instructions, output_type), message, max_turns=1, run_config=_RUN
            )
        return result.final_output_as(output_type, raise_if_incorrect_type=True)


@lru_cache
def openai_drafter(model: str, api_key: str) -> OpenAIDrafter:
    return OpenAIDrafter(model, openai.AsyncOpenAI(api_key=api_key))


def get_drafter() -> Drafter:
    s = get_settings()
    if not s.openai_api_key:
        raise DrafterError(503, "not_configured", "AI drafting isn't configured (OPENAI_API_KEY).")
    return openai_drafter(s.drafter_model, s.openai_api_key)
