"""What the orchestrator's model calls return (strict structured outputs)."""

from typing import Literal

from pydantic import BaseModel


class SubjectPick(BaseModel):
    subject_id: str | None
    confidence: float
    reason: str


class AgentScore(BaseModel):
    handle: str
    score: float
    reason: str


class AgentScores(BaseModel):
    scores: list[AgentScore]
    multi_intent: bool


class Entity(BaseModel):
    type: str
    value: str


class Brief(BaseModel):
    goal: str
    entities: list[Entity]
    constraints: list[str]
    urgency: Literal["low", "normal", "high"]


class Intent(BaseModel):
    intent: Literal["chat", "status", "work"]


class SplitPart(BaseModel):
    handle: str
    text: str


class SplitResult(BaseModel):
    parts: list[SplitPart]
