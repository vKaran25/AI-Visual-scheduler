from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith("sqlite:///"):
    sqlite_path = Path(DATABASE_URL.replace("sqlite:///", ""))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def _run_migrations() -> None:
    """Apply idempotent, recorded upgrades; surface unexpected DDL failures."""
    from sqlalchemy import inspect, text

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
        applied = set(conn.execute(text("SELECT version FROM schema_migrations")).scalars())
        if 1 not in applied:
            columns = [
                ("memory", "chat_session_id", "TEXT"),
                ("agentsession", "title", "TEXT NOT NULL DEFAULT ''"),
                ("agentsession", "calendar_snapshot", "TEXT NOT NULL DEFAULT ''"),
                ("agentsession", "last_accessed_at", "TIMESTAMP"),
                ("agentsession", "finished_at", "TIMESTAMP"),
            ]
            known = {}
            for table, col, definition in columns:
                if table not in known:
                    known[table] = {item["name"] for item in inspect(conn).get_columns(table)}
                if col not in known[table]:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
                    known[table].add(col)
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (1)"))
        if 2 not in applied:
            conn.execute(text("UPDATE memory SET type = 'pref' WHERE type = 'preference'"))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (2)"))
        if 3 not in applied:
            existing = {item["name"] for item in inspect(conn).get_columns("agentsession")}
            if "draft_revision" not in existing:
                conn.execute(text("ALTER TABLE agentsession ADD COLUMN draft_revision TEXT"))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (3)"))


def create_db_and_tables() -> None:
    import app.db.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _run_migrations()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

