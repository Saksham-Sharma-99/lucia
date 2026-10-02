"""Request and response models of the drafter API. Nothing here is stored."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from lucia.core.schema import PolicyRuleRef, Strict
from lucia.studio.config_schema import (
    MAX_PROMPT,
    AlertPolicy,
    Capability,
    EndConditions,
    FollowUp,
    Hitl,
    Recurrence,
)
from lucia.studio.schemas import Text, UseCases

Section = Literal["capabilities", "policies", "schedules"]
Prompt = Annotated[str, Field(min_length=1, max_length=MAX_PROMPT)]


class Basic(Strict):
    name: Annotated[str, Field(max_length=120)] = ""
    description: Text = ""
    use_cases: UseCases = []


class DraftContext(Strict):
    """What the person already has on the other steps. Unset (null) means not reached yet."""

    capabilities: list[Capability] | None = None
    policy_pack: list[PolicyRuleRef] | None = None
    hitl: Hitl | None = None
    alert_policy: AlertPolicy | None = None
    follow_up: FollowUp | None = None
    recurrence: Recurrence | None = None
    end_conditions: EndConditions | None = None
    max_turns_per_episode: int | None = Field(default=None, ge=1, le=50)


class PromptDraftRequest(Strict):
    instruction: Annotated[str, Field(min_length=1, max_length=4000)]
    basic: Basic = Basic()
    current_prompt: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None  # set: refine it
    context: DraftContext | None = None


class PromptDelta(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class PromptDone(BaseModel):
    type: Literal["done"] = "done"
    prompt: str


class PromptFailed(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


PromptEvent = Annotated[PromptDelta | PromptDone | PromptFailed, Field(discriminator="type")]


class SectionDraftRequest(Strict):
    section: Section
    system_prompt: Prompt
    basic: Basic = Basic()
    upstream: DraftContext = DraftContext()


class _Draft(BaseModel):
    rationale: str
    unmapped: list[str]  # what the prompt asked for that the platform can't do


class CapabilitiesDraft(_Draft):
    section: Literal["capabilities"] = "capabilities"
    capabilities: list[Capability]


class PoliciesDraft(_Draft):
    section: Literal["policies"] = "policies"
    policy_pack: list[PolicyRuleRef]
    hitl: Hitl
    alert_policy: AlertPolicy


class SchedulesDraft(_Draft):
    section: Literal["schedules"] = "schedules"
    follow_up: FollowUp
    recurrence: Recurrence | None
    end_conditions: EndConditions
    max_turns_per_episode: int


SectionDraft = Annotated[
    CapabilitiesDraft | PoliciesDraft | SchedulesDraft, Field(discriminator="section")
]
