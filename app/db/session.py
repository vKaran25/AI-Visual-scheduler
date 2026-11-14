"""PostgreSQL units of work. Schema changes run through app.db.migrate."""

from typing import Generator

from sqlalchemy import inspect
from sqlmodel import Session, create_engine

from app.core.config import DATABASE_URL, psycopg_url

engine = create_engine(
    psycopg_url(DATABASE_URL),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=2,
    connect_args={
        "connect_timeout": 10,
        **({"prepare_threshold": None} if "-pooler" in DATABASE_URL else {}),
    },
)


def verify_schema() -> None:
    if not inspect(engine).has_table("alembic_version"):
        raise RuntimeError("Database is not initialized. Run: python -m app.db.migrate")
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.core.config import BASE_DIR

    expected = ScriptDirectory.from_config(Config(str(BASE_DIR / "alembic.ini"))).get_current_head()
    with engine.connect() as connection:
        actual = MigrationContext.configure(connection).get_current_revision()
    if actual != expected or not inspect(engine).has_table("checkpoints"):
        raise RuntimeError("Database schema is out of date. Run: python -m app.db.migrate")


def get_session() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
