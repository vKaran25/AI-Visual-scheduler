# Predestination - AI Visual Scheduler

Predestination is a FastAPI visual scheduler with user accounts, database-backed blocks, reusable presets, Google Calendar sync, and a pure-Python agent layer for creating pending study plans with NVIDIA NIM.

The project is intentionally educational: agents are plain Python classes, scheduler tools are normal functions, and all user data is scoped by `user_id`.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://127.0.0.1:8000`.

## Environment

Required for local auth/database:

```env
DATABASE_URL=sqlite:///./data/scheduler.db
JWT_SECRET_KEY=change_me_to_a_long_random_secret
APP_BASE_URL=http://127.0.0.1:8000
```

Required for agents:

```env
NVIDIA_API_KEY=your_key
NVIDIA_NIM_MODEL=openai/gpt-oss-120b
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
```

Required for Google Calendar:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=
```

## Main Features

- Email/password signup and login with HttpOnly auth cookies.
- User-owned schedule blocks stored in SQLite locally.
- One block per time slot, with overlap checks for manual blocks, presets, and pending agent blocks.
- Free-time search that ignores gaps shorter than 30 minutes.
- Built-in presets: Blank, Student, Exam Prep, Working Professional, and Fitness + Study.
- Custom presets saved permanently in the database.
- Pure-Python NVIDIA NIM agent flow that creates pending blocks first, then commits only after confirmation.
- Short-term agent sessions and long-term user memory tables.
- Basic eval-run storage for future workflow evaluation.

## Project Structure

```text
app/
  api/        FastAPI routes for auth, scheduler, presets, memory, agents, Google, evals
  agents/    Pure-Python agent orchestration
  core/      Settings loaded from environment variables
  db/        SQLModel database engine and tables
  schemas/   Pydantic request/response models
  services/  Scheduler, auth, preset, memory, LLM, calendar, eval logic
tests/       API and service tests
index.html   Existing frontend, kept as a single page during this transition
app.py       Local dev runner
```

## API Surface

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`
- `GET /api/slots`
- `POST /api/slots`
- `PUT /api/slots/{slot_id}`
- `DELETE /api/slots/{slot_id}`
- `GET /api/free`
- `GET /api/presets`
- `POST /api/presets/{preset_id}/apply`
- `POST /api/custom-presets`
- `PUT /api/custom-presets/{preset_id}`
- `DELETE /api/custom-presets/{preset_id}`
- `POST /api/agent/chat`
- `POST /api/agent/confirm`
- `POST /api/agent/reject`
- `GET /api/memory`
- `POST /api/memory`
- `DELETE /api/memory/{memory_id}`

## Testing

```bash
pytest
```

The tests use a temporary SQLite database and mock the NIM LLM call.

## Docker

```bash
docker build -t predestination .
docker run --env-file .env -p 8000:8000 predestination
```

For deployment, SQLite is fine for a single instance with persistent disk. For a real multi-user deployment, set `DATABASE_URL` to a Postgres database and set `COOKIE_SECURE=true` behind HTTPS.
