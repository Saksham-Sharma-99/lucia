"""What the model returns for each section, and how that becomes a draft.

Each section has a static output model with a `to_draft()`. Per request, `output_model()`
narrows its id fields to the registry's values as enums, so the model can only pick tools,
rules and channels that exist. OpenAI strict structured outputs need every field required and
no open dicts, so rule params sit flat on one model per rule and a map param is a list of pairs.

Drafts are mapped as given: anything inconsistent (a dynamic follow-up without settings, min
above max) shows up as a validation issue in the form, like a hand edit would.
"""

import operator
from collections.abc import Iterable
from functools import reduce
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, WithJsonSchema, create_model

from lucia.core.schema import AlertChannel, PolicyRuleRef, Urgency
from lucia.db.models import RegistryEntry
from lucia.registry.catalog import CHANNEL_TOOLS
from lucia.registry.snapshot import RegistrySnapshot
from lucia.studio.config_schema import (
    AlertPolicy,
    Capability,
    Dynamic,
    EndConditions,
    EscalateAfter,
    FollowUp,
    Hitl,
    LadderRung,
    Recurrence,
)
from lucia.studio.drafter import schemas as s


def _enum_schema(*values: str) -> WithJsonSchema:
    """Render as a plain enum: pydantic writes `const` for a one-value Literal."""
    return WithJsonSchema({"type": "string", "enum": list(values)})


def _enum(values: Iterable[str]) -> Any:
    """A Literal of `values`, built at runtime from the registry."""
    vals = tuple(values)
    literal = Literal.__getitem__(vals)  # pyright: ignore[reportAttributeAccessIssue]
    return Annotated[literal, _enum_schema(*vals)]


def _narrow[M: BaseModel](base: type[M], **types: Any) -> type[M]:
    """`base` with some fields retyped, keeping their constraints and descriptions."""
    fields: dict[str, Any] = {name: (t, base.model_fields[name]) for name, t in types.items()}
    return create_model(base.__name__, __base__=base, **fields)


def follow_up_channels(tools: Iterable[str]) -> list[str]:
    """Channels whose send tool the agent has: the only ones a follow-up may use."""
    selected = set(tools)
    return [ch for ch, tool in CHANNEL_TOOLS.items() if tool in selected]


class _Out(BaseModel):
    rationale: str = Field(description="1-3 plain sentences: why these choices.")
    unmapped: list[str] = Field(
        description="What the prompt asks for that the platform can't do. Short; empty if none."
    )


# Capabilities


class CapabilitiesOut(_Out):
    tools: list[str] = Field(description="Every tool the agent needs, and no others.")

    def to_draft(self) -> s.CapabilitiesDraft:
        by_connector: dict[str, list[str]] = {}
        for name in dict.fromkeys(self.tools):  # tool names are "<connector>.<tool>"
            by_connector.setdefault(name.split(".", 1)[0], []).append(name)
        return s.CapabilitiesDraft(
            capabilities=[Capability(connector=c, tools=t) for c, t in by_connector.items()],
            rationale=self.rationale,
            unmapped=self.unmapped,
        )


# Policies


class RuleOut(BaseModel):
    rule: str

    def ref(self) -> PolicyRuleRef:
        params = self.model_dump(exclude={"rule"}, exclude_none=True)
        return PolicyRuleRef(rule=self.rule, params=params)


class Pair(BaseModel):
    key: str
    value: Any


class MapRuleOut(RuleOut):
    """A rule whose params are a map (document kind -> roles), sent as a list of pairs."""

    entries: list[Pair]

    def ref(self) -> PolicyRuleRef:
        return PolicyRuleRef(rule=self.rule, params={e.key: e.value for e in self.entries})


def _param_type(schema: dict[str, Any]) -> Any:
    """The subset of JSON Schema that policy rule params use."""
    match schema.get("type"):
        case "string" if "enum" in schema:
            return _enum(schema["enum"])
        case "string":
            return Annotated[str, Field(pattern=schema.get("pattern"))]
        case "integer":
            return Annotated[int, Field(ge=schema.get("minimum"), le=schema.get("maximum"))]
        case "array":
            item = _param_type(schema["items"])
            return Annotated[list[item], Field(min_length=schema.get("minItems"))]
        case _:
            raise ValueError(f"The drafter can't express this param schema: {schema}")


def rule_model(entry: RegistryEntry) -> type[RuleOut]:
    """An output model for one policy rule, with its params as typed fields."""
    schema = entry.params_schema
    name = "".join(part.title() for part in entry.name.split("_"))
    fields: dict[str, Any] = {"rule": (_enum([entry.name]), ...)}
    if isinstance(value := schema.get("additionalProperties"), dict):
        pair = create_model(f"{name}Entry", __base__=Pair, value=(_param_type(value), ...))
        fields["entries"] = (list[pair], ...)
        base: type[RuleOut] = MapRuleOut
    else:
        required = set(schema.get("required", []))
        for key, prop in schema.get("properties", {}).items():
            typ = _param_type(prop)
            fields[key] = (typ if key in required else typ | None, ...)
        base = RuleOut
    return create_model(name, __base__=base, __doc__=entry.description, **fields)


class PoliciesOut(_Out):
    rules: list[RuleOut]
    ask_on: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")]] = Field(
        description="snake_case situations where the agent stops and asks a person."
    )
    verify_evidence_below: float = Field(
        ge=0, le=1, description="Ask a person to verify evidence below this confidence (0.8)."
    )
    urgency_mode: Literal["auto", "fixed"]
    fixed_urgency: Urgency | None = Field(description="Only when urgency_mode is fixed.")
    p0_channels: list[AlertChannel] = Field(description="Where P0 (urgent) alerts go.")
    p1_channels: list[AlertChannel]
    p2_channels: list[AlertChannel]

    def to_draft(self) -> s.PoliciesDraft:
        channels: dict[Urgency, list[str]] = {
            "P0": list(self.p0_channels),
            "P1": list(self.p1_channels),
            "P2": list(self.p2_channels),
        }
        return s.PoliciesDraft(
            policy_pack=[r.ref() for r in self.rules],
            hitl=Hitl(ask_on=self.ask_on, verify_evidence_below=self.verify_evidence_below),
            alert_policy=AlertPolicy(
                urgency_mode=self.urgency_mode,
                fixed_urgency=self.fixed_urgency if self.urgency_mode == "fixed" else None,
                default_channels=channels,
            ),
            rationale=self.rationale,
            unmapped=self.unmapped,
        )


# Schedules


class _RungOut(BaseModel):
    wait_hours: int = Field(ge=0, le=24 * 60, description="Wait before this step.")
    attempts: int = Field(ge=1, le=10)
    urgency: Urgency | None


class ChannelRungOut(_RungOut):
    kind: Annotated[Literal["channel"], _enum_schema("channel")]
    channel: str

    def to_rung(self) -> LadderRung:
        return LadderRung(
            channel=self.channel,
            wait_hours=self.wait_hours,
            attempts=self.attempts,
            urgency=self.urgency,
        )


class ActionRungOut(_RungOut):
    kind: Annotated[Literal["action"], _enum_schema("action")]
    action: Literal["escalate", "flag"]

    def to_rung(self) -> LadderRung:
        return LadderRung(
            action=self.action,
            wait_hours=self.wait_hours,
            attempts=self.attempts,
            urgency=self.urgency,
        )


class DynamicOut(BaseModel):
    min_hours: int = Field(ge=1, le=24 * 60)
    max_hours: int = Field(ge=1, le=24 * 60)
    business_hours: bool
    channels: list[str] = Field(min_length=1)
    escalate_after_attempts: int = Field(ge=1, le=20)
    escalate_urgency: Urgency

    def to_dynamic(self) -> Dynamic:
        return Dynamic(
            min_hours=self.min_hours,
            max_hours=self.max_hours,
            business_hours=self.business_hours,
            channels=self.channels,
            escalate_after=EscalateAfter(
                attempts=self.escalate_after_attempts, urgency=self.escalate_urgency
            ),
        )


class SchedulesOut(_Out):
    mode: Literal["none", "fixed_ladder", "dynamic"] = Field(
        description="fixed_ladder: set steps. dynamic: the agent picks timing."
    )
    # A plain union: pydantic tells the steps apart by `kind`. A `discriminator` would leave a
    # keyword in the JSON schema that OpenAI strict mode may reject.
    ladder: list[ChannelRungOut | ActionRungOut] = Field(description="Only for fixed_ladder.")
    dynamic: DynamicOut | None = Field(description="Only for dynamic.")
    recurrence_every_days: int | None = Field(
        ge=1, le=365, description="Start a new cycle every N days; null for one-off work."
    )
    max_duration_days: int = Field(ge=1, le=730)
    max_steps: int = Field(ge=10, le=5000)
    on_subject_closed: Literal["end", "pause"]
    max_turns_per_episode: int = Field(ge=1, le=50)

    def to_draft(self) -> s.SchedulesDraft:
        """Only the settings of the chosen mode are kept, as the form does."""
        ladder = [r.to_rung() for r in self.ladder] if self.mode == "fixed_ladder" else []
        dynamic = self.dynamic.to_dynamic() if self.mode == "dynamic" and self.dynamic else None
        every = self.recurrence_every_days
        return s.SchedulesDraft(
            follow_up=FollowUp(mode=self.mode, ladder=ladder, dynamic=dynamic),
            recurrence=Recurrence(every_days=every) if every else None,
            end_conditions=EndConditions(
                max_duration_days=self.max_duration_days,
                max_steps=self.max_steps,
                on_subject_closed=self.on_subject_closed,
            ),
            max_turns_per_episode=self.max_turns_per_episode,
            rationale=self.rationale,
            unmapped=self.unmapped,
        )


SectionOut = CapabilitiesOut | PoliciesOut | SchedulesOut


def output_model(section: s.Section, snap: RegistrySnapshot, tools: list[str]) -> type[SectionOut]:
    """The section's output model, with its id fields narrowed to what the registry has."""
    match section:
        case "capabilities":
            available = _enum(name for name, t in snap.tools.items() if t.available)
            return _narrow(CapabilitiesOut, tools=list[available])
        case "policies":
            rules = [rule_model(e) for e in snap.policy_rules.values() if e.available]
            rule = reduce(operator.or_, rules) if rules else RuleOut
            return _narrow(PoliciesOut, rules=Annotated[list[rule], Field(max_length=len(rules))])
        case "schedules":
            channels = follow_up_channels(tools)
            if not channels:  # nothing to follow up with
                return _narrow(SchedulesOut, mode=_enum(["none"]))
            channel = _enum(channels)
            return _narrow(
                SchedulesOut,
                ladder=list[_narrow(ChannelRungOut, channel=channel) | ActionRungOut],
                dynamic=_narrow(DynamicOut, channels=list[channel]) | None,
            )
