# PostgreSQL setup and migration tutorial

A **schema migration** is a versioned change to database tables, indexes, or constraints. A **data migration** transforms or copies records. This release starts fresh and does not copy the old SQLite database.

## Database setup

Use PostgreSQL 16 or later. The easiest local option is `scripts/dev.py up`, which runs an embedded PostgreSQL inside
the project's virtual environment. Any PostgreSQL works if you set the URLs in `.env`.

1. Set `DATABASE_URL` (application connections) and `DATABASE_DIRECT_URL` (migrations and checkpoints). They can be the
   same URL.
2. Keep TLS parameters such as `sslmode=require` if your server needs them.
3. Set a private `JWT_SECRET_KEY` in `.env`.
4. Run `python -m app.db.migrate` before starting the API and worker (`scripts/dev.py up` does this for you).

The command applies Alembic application migrations and then initializes/upgrades the pinned LangGraph checkpoint schema. API startup checks the schema; it does not run DDL.

A small direct pool is used for checkpoints. The application does not depend on session advisory locks, so it also works behind a transaction-mode connection pooler.

## Making a future schema change

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
# Review the generated revision, including types, constraints, and any data conversion.
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

Review generated migrations before committing. Historical migrations use frozen SQLAlchemy types rather than importing evolving application models.

Use a development database first. Back up production before destructive changes. A downgrade that removes records is not a safe rollback after users have written new data; prefer a forward repair migration.

## Tests

`TEST_DATABASE_URL` must reference a dedicated database ending in `_test`. The test fixture refuses other names and truncates application records between integration tests. Never point it at a database containing user data.

## Existing records

Existing SQLite files are left untouched but are no longer opened by the application. Users register again and reconnect Google. No script silently deletes the old database.
