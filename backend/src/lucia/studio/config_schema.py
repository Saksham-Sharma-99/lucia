"""The version config (backend-plan §6). Structure only; validator.py checks the registry."""

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema
from pydantic_core import PydanticCustomError

from lucia.core.schema import PolicyRuleRef, Strict, Urgency

RESERVED_KEYS = ("task_templates", "finding_schema", "state_schema")
MAX_PROMPT = 20000


class Models(Strict):
    loop: str
    guardrail: str
    judge: str


class Capability(Strict):
    connector: str
    tools: list[str] = Field(min_length=1)


class LadderRung(Strict):
    channel: str | None = None
    action: Literal["escalate", "flag"] | None = None
    wait_hours: int | float = Field(ge=0, le=24 * 60)  # decimals allowed: 0.1 h = 6 min
    attempts: int = Field(default=1, ge=1, le=10)
    urgency: Urgency | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "LadderRung":
        if (self.channel is None) == (self.action is None):
            raise PydanticCustomError("rung_kind", "Set exactly one of channel or action")
        return self


class EscalateAfter(Strict):
    attempts: int = Field(ge=1, le=20)
    urgency: Urgency


class Dynamic(Strict):
    min_hours: int | float = Field(gt=0, le=24 * 60)
    max_hours: int | float = Field(gt=0, le=24 * 60)
    business_hours: bool = True
    channels: list[str] = Field(min_length=1)
    escalate_after: EscalateAfter


class FollowUp(Strict):
    mode: Literal["none", "fixed_ladder", "dynamic"] = "none"
    ladder: list[LadderRung] = []
    dynamic: Dynamic | None = None


class Recurrence(Strict):
    every_days: int | float = Field(ge=0, le=365)  # decimals allowed: 0.5 = 12 h; 0 = back to back
    # Stop after this many rounds (then a person confirms completion). Unset: no limit, and not
    # stored, so versions saved before this field keep their config hash.
    max_cycles: int | None = Field(default=None, ge=1, le=1000, exclude_if=lambda v: v is None)


class EndConditions(Strict):
    max_duration_days: int = Field(default=120, ge=1, le=730)
    max_steps: int = Field(default=600, ge=10, le=5000)
    on_subject_closed: Literal["end", "pause"] = "end"


class Hitl(Strict):
    ask_on: list[str] = []
    verify_evidence_below: float = Field(default=0.8, ge=0, le=1)


class AlertPolicy(Strict):
    urgency_mode: Literal["auto", "fixed"] = "auto"
    fixed_urgency: Urgency | None = None
    default_channels: dict[Urgency, list[str]]


class VersionConfig(Strict):
    system_prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    models: Models
    capabilities: list[Capability] = Field(min_length=1)
    follow_up: FollowUp = FollowUp()
    recurrence: Recurrence | None = None
    end_conditions: EndConditions = EndConditions()
    policy_pack: list[PolicyRuleRef] = []
    hitl: Hitl = Hitl()
    alert_policy: AlertPolicy
    max_turns_per_episode: int = Field(default=12, ge=1, le=50)

    # Reserved for the runtime phase: accepted by name only so the error says why.
    task_templates: SkipJsonSchema[Any] = Field(default=None, exclude=True)
    finding_schema: SkipJsonSchema[Any] = Field(default=None, exclude=True)
    state_schema: SkipJsonSchema[Any] = Field(default=None, exclude=True)

    @field_validator(*RESERVED_KEYS)
    @classmethod
    def _reserved(cls, value: Any) -> None:
        if value is not None:
            raise PydanticCustomError("reserved", "Not available in this phase")
        return None

    def stored(self) -> dict[str, Any]:
        """The JSON that is saved and hashed."""
        return self.model_dump(mode="json")
