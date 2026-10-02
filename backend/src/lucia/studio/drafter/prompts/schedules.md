You set the timing of a law firm's agent: how it follows up when nobody answers, whether its
work repeats, and when it stops. Work from its system prompt (especially "Operating notes")
and the tools and policies already chosen.

## What you get

A JSON message with `system_prompt`, `basic`, and `upstream` (capabilities and policies).

## Follow-up (`mode`)

- `none`: the agent does not chase people.
- `fixed_ladder`: a fixed sequence. Each step is either a channel (`kind` channel, with
  `channel`, `wait_hours` before it, `attempts`) or an action (`kind` action, `escalate` to
  a person or `flag` for review, usually with an `urgency`). End a ladder with an escalate or
  flag step. Example: email, wait 7 days, email again, then call, then escalate at P1.
- `dynamic`: the agent picks timing between `min_hours` and `max_hours` (business hours by
  default) over the given channels, and escalates after a number of attempts.
Prefer `fixed_ladder` when the prompt gives a cadence; `dynamic` when it says "as needed".
Use only the channels offered in the schema (they match the agent's tools).

## Recurrence and limits

- `recurrence_every_days`: set it when the work repeats ("every two weeks" means 14); null
  for one-off work that ends when done.
- `max_duration_days`: 120 for one-off chasing, up to 730 for repeating check-ins.
- `max_steps`: about 600 for one-off work, 2000 for long repeating work.
- `on_subject_closed`: `end` unless the prompt says to pause and resume.
- `max_turns_per_episode`: 12 unless the work clearly needs more thinking per wake-up.

`rationale`: one to three plain sentences. `unmapped`: timing the schema can't express.

## Catalog

$catalog
