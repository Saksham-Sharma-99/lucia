# CLAUDE.md

Lucia is a builder for long-running AI agents: Studio (builder UI and API) plus a durable runtime (harness). See README.md for the architecture, layout and commands.

## Source of truth

Before building or changing anything, read the relevant design docs in the local `docs/` folder (gitignored, but present on disk):

- `docs/PRD.md` and `docs/HLD.md`
- `docs/features/<feature>/` (prd, hld, lld, decisions, bottlenecks, improvements)
- `docs/features/_shared/contracts.md` (table ownership, enums, shared names)

Rules:

- The entity set and relationships in HLD §7 are locked. Do not add, rename or restructure entities, or change relationships, without asking first.
- If the code, the docs and the request disagree, stop and ask. Explain the discrepancy and wait for a decision.
- When behavior changes, update the relevant docs in the same change.

## Workflow

- Write unit tests and integration tests for everything you build.
- Before saying something is done, run `make lint typecheck test`, and exercise the actual behavior: call the endpoint, run the task, open the page.
- Migrations: `make migration m="..."`, then review the generated file.
- After any API change, run `make gen-client` (with `make dev-api` running) and commit the regenerated client.
- Local infra: `make db-up`. Postgres is on localhost:5433, Redis on 6379.

## Code conventions

Python (backend/src/lucia):

- Fully typed; pyright must pass.
- Async SQLAlchemy 2. Use pydantic models at API edges, never ORM objects.
- Access firm data only through firm-scoped repositories. No query may read or write across firms.
- Celery tasks must be idempotent; schedule through the Episode model described in HLD §10.

TypeScript (frontend/src):

- Read data only through TanStack Query with the generated client (`src/api/generated`). Never call `fetch` directly.
- Use shadcn/ui components (`pnpm dlx shadcn@latest add <name>`) and Tailwind. Routes are file-based under `src/routes`.

## Safety

- Never commit secrets or `.env` files. Keep the `.env.example` files up to date instead.
- Every external send (email, call, message) goes through the ToolExecutor with a deterministic idempotency key.
- No PHI or message bodies in logs.
- Ask before schema or entity changes, adding dependencies, or any destructive git or database operation.

## Git

- Never run `git commit`; the user commits. Stage nothing unless asked.
- When suggesting a commit message, use Conventional Commits (`feat:`, `fix:`, `chore:`, ...).

## Style

- Keep code, tests and docs to the point. Add no speculative abstractions, unused helpers, or tests that only assert the obvious.
- Match the surrounding code's naming, comment density and structure.
- Simplicity over complexity.
- Always test and review your code.
- Always research over internet for best practices.
- Never assume. always ask if you're unsure.
