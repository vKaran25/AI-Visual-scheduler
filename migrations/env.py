"""Alembic manages application tables; checkpoint setup is a release step."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import app.db.models  # noqa: F401
from app.core.config import DATABASE_DIRECT_URL, psycopg_url

target_metadata = SQLModel.metadata


def include_object(obj, name, type_, reflected, compare_to):
    return not reflected or name in target_metadata.tables


if context.is_offline_mode():
    context.configure(
        url=psycopg_url(DATABASE_DIRECT_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(psycopg_url(DATABASE_DIRECT_URL), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
