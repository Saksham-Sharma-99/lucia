"""Runtime model calls through the OpenAI Agents SDK: structured, text, or one forced tool call.

Nothing is stored (`store=False`) and traces never include prompts. Every call returns `Usage`
so the harness can record model, latency, tokens and cost per step (RUNTIME_SPEC §10.2).
"""

import asyncio
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from weakref import WeakKeyDictionary

import openai
from agents import (
    Agent,
    AgentsException,
    FunctionTool,
    ModelSettings,
    OpenAIResponsesModel,
    RunContextWrapper,
    Runner,
)
from agents.run import RunConfig
from pydantic import BaseModel

from lucia.core.config import get_settings

_RUN = RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)


@dataclass(frozen=True)
class Usage:
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost: Decimal


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLM(Protocol):
    async def structured[T: BaseModel](
        self,
        *,
        role: str,
        model: str,
        instructions: str,
        message: str,
        output_type: type[T],
        seconds: float = 30,
    ) -> tuple[T, Usage]: ...

    async def text(
        self, *, role: str, model: str, instructions: str, message: str, seconds: float = 30
    ) -> tuple[str, Usage]: ...

    async def tool_call(
        self,
        *,
        role: str,
        model: str,
        instructions: str,
        message: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        seconds: float = 30,
    ) -> tuple[dict[str, Any], Usage]:
        """One forced call of `tool_name`; returns the arguments the model chose (not executed)."""
        ...


def sdk_tool_name(tool: str) -> str:
    return tool.replace(".", "__")


def _cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    per_m_in, per_m_out = get_settings().llm_costs.get(model, (0.0, 0.0))
    return Decimal(str((input_tokens * per_m_in + output_tokens * per_m_out) / 1_000_000))


class OpenAILLM:
    def __init__(self, client: openai.AsyncOpenAI) -> None:
        self.client = client

    async def _run(
        self, agent: Agent[None], message: str, model: str, seconds: float
    ) -> tuple[Any, Usage]:
        started = time.monotonic()
        try:
            async with asyncio.timeout(seconds):
                result = await Runner.run(agent, message, max_turns=2, run_config=_RUN)
        except (TimeoutError, openai.APITimeoutError) as e:
            raise LLMError("model call timed out", retryable=True) from e
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError) as e:
            raise LLMError(type(e).__name__, retryable=True) from e
        except (AgentsException, openai.OpenAIError) as e:
            raise LLMError(type(e).__name__, retryable=False) from e
        u = result.context_wrapper.usage
        usage = Usage(
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cost=_cost(model, u.input_tokens, u.output_tokens),
        )
        return result.final_output, usage

    def _agent(self, model: str, instructions: str, **kwargs: Any) -> Agent[None]:
        settings = kwargs.pop("model_settings", ModelSettings())
        return Agent(
            name="lucia",
            instructions=instructions,
            model=OpenAIResponsesModel(model, self.client),
            model_settings=settings.resolve(ModelSettings(store=False)),
            **kwargs,
        )

    async def structured[T: BaseModel](
        self,
        *,
        role: str,
        model: str,
        instructions: str,
        message: str,
        output_type: type[T],
        seconds: float = 30,
    ) -> tuple[T, Usage]:
        agent = self._agent(model, instructions, output_type=output_type)
        out, usage = await self._run(agent, message, model, seconds)
        if not isinstance(out, output_type):
            raise LLMError("model output had the wrong type", retryable=False)
        return out, usage

    async def text(
        self, *, role: str, model: str, instructions: str, message: str, seconds: float = 30
    ) -> tuple[str, Usage]:
        out, usage = await self._run(self._agent(model, instructions), message, model, seconds)
        return str(out), usage

    async def tool_call(
        self,
        *,
        role: str,
        model: str,
        instructions: str,
        message: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        seconds: float = 30,
    ) -> tuple[dict[str, Any], Usage]:
        name = sdk_tool_name(tool_name)

        async def capture(_: RunContextWrapper[Any], args: str) -> str:
            return args

        tool = FunctionTool(
            name=name,
            description=f"Call {tool_name}.",
            params_json_schema=tool_schema,
            on_invoke_tool=capture,
            strict_json_schema=False,
        )
        agent = self._agent(
            model,
            instructions,
            tools=[tool],
            tool_use_behavior="stop_on_first_tool",
            model_settings=ModelSettings(tool_choice=name, parallel_tool_calls=False),
        )
        out, usage = await self._run(agent, message, model, seconds)
        try:
            args = json.loads(out)
        except (TypeError, ValueError) as e:
            raise LLMError("model did not call the tool", retryable=False) from e
        return args, usage


_override: LLM | None = None
# One client per event loop: its pooled connections belong to the loop that opened them, and
# each Celery task runs in a fresh loop (worker/runner.py), so a shared client breaks the next
# task with "Event loop is closed".
_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, OpenAILLM] = WeakKeyDictionary()


def get_llm() -> LLM:
    if _override is not None:
        return _override
    key = get_settings().openai_api_key
    if not key:
        raise LLMError("OPENAI_API_KEY is not set", retryable=False)
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        _clients[loop] = OpenAILLM(openai.AsyncOpenAI(api_key=key, max_retries=0, timeout=60))
    return _clients[loop]


async def close_llm() -> None:
    """Closes the current loop's client (a task's last step, before its loop ends)."""
    if llm := _clients.pop(asyncio.get_running_loop(), None):
        await llm.client.close()


def set_llm(llm: LLM | None) -> None:
    """Tests install a FakeLLM; None restores the real client."""
    global _override
    _override = llm
