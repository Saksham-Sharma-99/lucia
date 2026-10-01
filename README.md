# Lucia

Lucia is a builder for long-running AI agents: agents whose work spans days or weeks, follows up across email, chat and phone, reacts to replies, and pulls in a human only when it is blocked or something meaningful happens.

A builder defines an agent as configuration, including:
- its capabilities
- task templates and success criteria
- follow-up policy
- tools and compliance rules
- eval cases

They prove it in a simulator on a virtual clock, publish a read-only version, and map that version to a customer organization with its own identities (mailbox, Slack bot, phone number). One shared runtime runs every agent durably, with human-in-the-loop, audit and live evals built in.

**Who it's for:** teams that need many workflows shaped like "pursue a goal for weeks, follow up, escalate when stuck, report what matters", and want each new use case to be a config file rather than a new engineering project. The first use cases are legal operations (medical-records follow-up, client check-ins, lien follow-ups), but nothing in the platform is specific to them.

## Architecture

```
 Studio (React)                    Slack · Gmail · Vapi · Public API
      │                                          │
      ▼                                          ▼
 FastAPI ── builder: agents, capabilities,    FastAPI ── ingress: normalize → correlate → Episode
            versions, validator, compiler,                │
            evals/simulator, firm mappings               ▼ Celery (Redis)
      │                                      Harness worker: lease → context → Agents SDK
      └────────── published version ───────► run → ToolExecutor (policy, guardrail,
                                              idempotent outbox, connectors) → close
                                                          │
                              Postgres (configs, versions, runs, audit) · object store (later)
```

- An **Agent** is global. Its **AgentPrompt** versions are read-only once published, and amending one creates a new version.
- A firm reaches an agent only through a **CompiledAgentFirmMapping**.
- An **AgentRun** lives for weeks. It is advanced by **Episodes** (scheduled follow-ups, inbound replies, human answers) and broken into **RunTasks** and **AgentRunSteps**.
- What a step produces for humans is a **StepResult**: a finding or an attention item.

The full design is in the local `docs/` folder (gitignored):
- `docs/PRD.md`: product requirements
- `docs/HLD.md`: high-level design and the locked entity model (§7)
- `docs/features/<feature>/`: PRD, HLD, LLD, decisions, bottlenecks and improvements per feature
- `docs/features/_shared/contracts.md`: cross-feature contracts (table ownership, enums, shared names)

## Repo layout

```
backend/            Python 3.12, uv, FastAPI, SQLAlchemy 2 (async), Alembic, Celery
  src/lucia/        api/ core/ db/ worker/ studio/ harness/ connectors/
  alembic/          migrations
  tests/
frontend/           Vite, React, TypeScript, Tailwind v4, shadcn/ui, TanStack Router + Query
  src/routes/       file-based routes
  src/api/generated typed client generated from the backend OpenAPI schema
infra/postgres/     init.sql (creates the lucia_test database)
docker-compose.yml  Postgres 16 + Redis 7 for local development
Makefile            all common tasks
```

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22 with pnpm 9, Docker, and [pre-commit](https://pre-commit.com/).

```bash
make setup        # uv sync, pnpm install, .env files from examples, git hooks
make db-up        # Postgres on localhost:5433, Redis on localhost:6379
make migrate      # apply migrations
make dev          # API :8000, Celery worker + beat, web :5173
```

Open http://localhost:5173. The Studio home page shows the API health, read through the generated client. The API docs are at http://localhost:8000/docs.

Postgres is published on host port 5433 because a natively installed Postgres often already holds 5432.

## Everyday commands

| Command | What it does |
| --- | --- |
| `make lint` / `make fmt` | ruff + eslint + prettier |
| `make typecheck` | pyright + tsc |
| `make test` | pytest against the `lucia_test` database |
| `make migration m="..."` | new Alembic migration (autogenerate) |
| `make gen-client` | regenerate the TS client after API changes (API must be running) |
| `make ci` | everything CI runs, locally |
| `make db-reset` | drop local data and start fresh |

CI (GitHub Actions) runs these on every pull request:
- backend: ruff, pyright, pytest and an Alembic check
- frontend: eslint, prettier, tsc and the build

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
