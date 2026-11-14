# Predestination — durable AI calendar

Predestination combines a LangGraph orchestrator and specialist workers with a bounded evaluator–optimizer loop. PostgreSQL stores calendar records, approvals, jobs, graph checkpoints, and Google synchronization state.

## Quick local demo (no Docker, no accounts)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt -c requirements.lock
.\.venv\Scripts\python.exe scripts\dev.py seed   # demo student account with a realistic week
.\.venv\Scripts\python.exe scripts\dev.py up     # embedded PostgreSQL + API + worker
```

Open <http://127.0.0.1:8000/home> (use `127.0.0.1`, not `localhost`) and sign in as
`student@example.com` (password: `DEMO_PASSWORD` in `app/demo_seed.py`). Manual scheduling, voice and the MCP
server work without any key; add a free `OPENROUTER_API_KEY` to `.env` for the assistant. Run the tests with
`scripts\dev.py test`, and the MCP server with `scripts\dev.py mcp`
(see [the prototype architecture](docs/demo-architecture.md)).

## Start locally

Use Python 3.12 and PostgreSQL 16 or later. No SQLite fallback or data import is performed.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements.lock
Copy-Item .env.example .env
```

Configure `DATABASE_URL`, `DATABASE_DIRECT_URL`, and a private `JWT_SECRET_KEY` in `.env`. Then:

```powershell
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
.\.venv\Scripts\python.exe -m app.runtime.worker
```

Open [the sign-in page](http://127.0.0.1:8000/home). Confirm the calendar timezone before planning. Manual scheduling works without a model key; the assistant needs `OPENROUTER_API_KEY`.

## What the assistant does

- Creates study plans and event proposals, answers availability questions, and proposes edits, deletions, and preset operations.
- Asks about missing times, AM/PM, durations, or planning availability.
- Evaluates complex proposals and repairs affected tasks within fixed limits.
- Saves calendar changes only after approval of the exact draft revision.
- Keeps drafts separate from confirmed availability.
- Suggests reusable preferences and waits for consent to remember them.
- Imports Google busy time and synchronizes app-created events through an outbox.
- Preserves month/week/day views, both visual styles, light/dark modes, manual forms, and the collapsible tools panel.

## Repository map

```text
app/
  agents/          LangGraph, specialist subgraph, prompts, state, context
  api/             Authenticated HTTP endpoints
  core/            Environment configuration
  db/              PostgreSQL records, sessions, transactions, migration command
  domain/          Typed contracts, interval arithmetic, timezone logic, OR-Tools
  evaluations/     Offline checks and labeled live evaluator benchmark
  integrations/    OpenRouter, bounded web research, Google OAuth/synchronization
  runtime/         Durable worker, leases, budgets, fenced checkpoints
  schemas/         Public API contracts
  services/        Calendar/preset commands, drafts, memory, runs, outbox
frontend/
  index.html       Planner markup
  landing.html     Sign-in and welcome markup
  assets/css/      Extracted planner, calendar, and landing styles
  assets/js/       Bootstrap, planner, calendar, durable agent UI, landing animation
migrations/        Reviewed, versioned Alembic schema revisions
tests/             Domain, PostgreSQL, graph recovery, integration, frontend checks
docs/              Architecture, API, migration notes, decisions and demo material
```

## Verification

Use a separate database whose name ends with `_test`; tests truncate application tables in that database.

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/scheduler_test?sslmode=require'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests migrations
.\.venv\Scripts\python.exe -m app.evaluations
```

The graph tests run the actual LangGraph and PostgreSQL checkpointer with mocked inference. Live OpenRouter and Google checks need configured credentials and are separate from offline verification.

- [Architecture and agent contracts](docs/architecture.md)
- [API and UI contracts](docs/api.md)
- [Database migration tutorial](docs/database.md)
- [Prototype architecture and MCP server](docs/demo-architecture.md)
