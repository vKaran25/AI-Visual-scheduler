# PostgreSQL setup and migration tutorial

A **schema migration** is a versioned change to database tables, indexes, or constraints. A **data migration** transforms or copies records. This release starts fresh and does not copy the old SQLite database.

## Neon setup

1. Create a Neon project and separate development/staging and production environments.
2. Copy the pooled connection string into `DATABASE_URL`.
3. Copy the direct connection string into `DATABASE_DIRECT_URL`.
4. Retain Neon's TLS parameters, such as `sslmode=require`.
5. Set private secrets in `.env` locally or the Render environment group. Generate a fresh JWT secret for this fresh-database cutover so cookies from the old user database cannot authenticate new user IDs.
6. Run `python -m app.db.migrate` before starting the API/worker.

The command applies Alembic application migrations and then initializes/upgrades the pinned LangGraph checkpoint schema. API startup checks the schema; it does not run DDL.

Pooled connections are used for short application transactions. A small direct pool is used for checkpoints. The application does not depend on session advisory locks through Neon's transaction pooler.

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
