"""Shared pydantic building blocks."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Urgency = Literal["P0", "P1", "P2"]
AlertChannel = Literal["slack_dm", "slack_thread", "email", "digest", "in_app"]
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class Strict(BaseModel):
    """Request and config models: unknown keys are errors, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class PolicyRuleRef(Strict):
    """A registry policy rule with its params (version packs and firm floors)."""

    rule: str
    params: dict[str, Any] = {}


class Read(BaseModel):
    """Response models built straight from ORM rows."""

    model_config = ConfigDict(from_attributes=True)
