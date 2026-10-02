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

```markdown
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

```markdown
backend/            Python 3.12, uv, FastAPI, SQLAlchemy 2 (async), Alembic, Celery
  src/lucia/        api/ core/ db/ worker/ studio/ harness/ connectors/
  alembic/          migrations
  tests/
frontend/           Vite, React, TypeScript, Tailwind v4, shadcn/ui, TanStack Router + Query
  src/routes/       file-based routes (thin: search-param validation, then a feature page)
  src/features/     one folder per area (agents, firms, mappings, registry, auth, shell)
  src/components/   shared/ app components, ui/ shadcn primitives
  src/lib/          API setup, problem+json handling, query invalidation, JSON-schema helpers
  src/api/generated typed client generated from the backend OpenAPI schema
  src/test/, e2e/   vitest + MSW helpers; Playwright smoke flows
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
make seed         # users, two firms, template agents, @orchestrator (prints generated passwords)
make dev          # API :8000, Celery worker + beat, web :5173
```

Open <http://localhost:5173> and sign in as a seeded user. The API is served under `/api/v1`; Swagger UI is at <http://localhost:8000/docs>.

**Studio** (the builder UI) has four areas:

- **Agents:** create agents from a template or blank, amend them into new versions, compare versions.
- **Firm mappings:** choose which agent version each firm runs, bind its connections, turn it on or off.
- **Firms:** firm settings and connections (Gmail and Slack consent links, Vapi numbers, live tests).
- **Registry:** the read-only catalog of connectors, tools and policy rules.

Seeded users (local development only):

| Username | Password |
| --- | --- |
| `saksham` | `lucia-dev` |
| `rishabh` | `lucia-dev` |

The password comes from `SEED_PASSWORD` in `backend/.env`, which `make setup` copies from `.env.example`. If `SEED_PASSWORD` is empty, `make seed` generates one password per user and prints it once. Seeding never changes the password of a user that already exists, so to apply a new `SEED_PASSWORD`, run `make db-reset`, then `make migrate` and `make seed`.

Postgres is published on host port 5433 because a natively installed Postgres often already holds 5432.

## Connecting integrations

[setup.md](setup.md) walks through every step: `.env`, Slack, Gmail, Vapi, the AI drafter and the public URL. In short:

App registrations are global and live in `backend/.env`. Each firm then connects its own mailbox, Slack workspace or phone number from the Firm → Connections page. `GET /api/v1/platform/status` shows which registrations are set.

OAuth redirects and webhooks need a public URL. In development:

1. Run `ngrok http 8000` and put the https URL in `PUBLIC_BASE_URL`.
2. **Slack:** create an app at api.slack.com/apps.
   - Bot scopes: `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `files:write`.
   - Redirect URL: `$PUBLIC_BASE_URL/api/v1/oauth/slack/callback`.
   - Event Subscriptions URL: `$PUBLIC_BASE_URL/api/v1/hooks/slack`, subscribed to `app_mention`.
   - Copy the client id, client secret and signing secret into `SLACK_*`.
3. **Gmail:** create a Web OAuth client in Google Cloud.
   - Redirect URI: `$PUBLIC_BASE_URL/api/v1/oauth/google/callback`.
   - Enable the Gmail API.
   - Create a Pub/Sub topic, grant `gmail-api-push@system.gserviceaccount.com` publish on it, and add a push subscription to `$PUBLIC_BASE_URL/api/v1/hooks/gmail?token=<GOOGLE_PUBSUB_VERIFICATION_TOKEN>`.
4. **Vapi (outbound calls only):**
   - Set `VAPI_API_KEY`.
   - Optionally set `VAPI_WEBHOOK_SECRET`. When it's set, each call sends it as `x-vapi-secret` and the webhook checks it. When it's empty, the webhook is open.
   - Import a number into Vapi (from Twilio, Telnyx or Vonage; Vapi's free numbers can't place calls) and set its id as `VAPI_PHONE_NUMBER_ID`, the default for every firm. A firm's Vapi connection can set its own number id instead.

Manual checklist (real APIs, not covered by `make test`):

- [ ] Install Slack from a consent link
- [ ] Run the auth test, then a `send_message` test
- [ ] Mention the bot, then retest `listen_mention`
- [ ] Gmail consent, then a `send_email` test
- [ ] Enable inbound, email the mailbox, then retest `list_inbox`
- [ ] Add a Vapi number, then place a test call

## Everyday commands

| Command | What it does |
| --- | --- |
| `make lint` / `make fmt` | ruff + eslint + prettier |
| `make typecheck` | pyright + tsc |
| `make test` | pytest against the `lucia_test` database (`UPDATE_SNAPSHOTS=1` accepts an OpenAPI change), then the frontend vitest suite |
| `make e2e` | Playwright smoke test of the main flows against a running `make dev` (set `E2E_PASSWORD` to the seed password). Afterwards it hard-deletes what the run created (agents `@e2e-*`, firms `e2e-firm-*`) with `uv run python -m lucia.seeds.cleanup_e2e` |
| `make seed` | idempotent seed data |
| `make migration m="..."` | new Alembic migration (autogenerate) |
| `make gen-client` | regenerate the TS client after API changes (API must be running) |
| `make ci` | everything CI runs, locally |
| `make db-reset` | drop local data and start fresh |

CI (GitHub Actions) runs these on every pull request:

- backend: ruff, pyright, pytest and an Alembic check
- frontend: eslint, prettier, tsc and the build

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
