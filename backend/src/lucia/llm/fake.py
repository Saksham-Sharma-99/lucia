"""A scripted LLM for tests: outputs are queued per role and returned in order."""

from collections import defaultdict, deque
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from lucia.llm.client import Usage

Scripted = BaseModel | str | dict[str, Any] | Exception


class FakeLLM:
    def __init__(self) -> None:
        self._queues: dict[str, deque[Scripted]] = defaultdict(deque)
        self.calls: list[tuple[str, str]] = []
        self.instructions: list[str] = []

    def on(self, role: str, *outputs: Scripted) -> None:
        self._queues[role].extend(outputs)

    def _next(self, role: str, message: str, model: str, instructions: str) -> tuple[Any, Usage]:
        self.calls.append((role, message))
        self.instructions.append(instructions)
        if not self._queues[role]:
            raise AssertionError(f"no scripted output for role {role}")
        out = self._queues[role].popleft()
        if isinstance(out, Exception):
            raise out
        return out, Usage(model, 5, 10, 5, Decimal("0.0001"))

    async def structured(
        self, *, role: str, model: str, instructions: str, message: str, **_: Any
    ) -> tuple[Any, Usage]:
        return self._next(role, message, model, instructions)

    async def text(
        self, *, role: str, model: str, instructions: str, message: str, **_: Any
    ) -> tuple[str, Usage]:
        out, usage = self._next(role, message, model, instructions)
        return str(out), usage

    async def tool_call(
        self, *, role: str, model: str, instructions: str, message: str, **_: Any
    ) -> tuple[dict[str, Any], Usage]:
        return self._next(role, message, model, instructions)
