"""Fence checkpoint writes with the same run lease used for domain writes."""

import os
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlmodel import Session

from app.core.config import DATABASE_DIRECT_URL, raw_postgres_url
from app.db.session import engine
from app.runtime.context import fence


class FencedPostgresSaver(PostgresSaver):
    def put(self, config, checkpoint, metadata, new_versions):
        with Session(engine) as db:
            fence(db)
            result = super().put(config, checkpoint, metadata, new_versions)
            db.commit()
            return result

    def put_writes(self, config, writes, task_id, task_path=""):
        with Session(engine) as db:
            fence(db)
            super().put_writes(config, writes, task_id, task_path)
            db.commit()


@contextmanager
def checkpoint_store():
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    with ConnectionPool(
        raw_postgres_url(DATABASE_DIRECT_URL),
        min_size=1,
        max_size=3,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        timeout=10,
    ) as pool:
        yield FencedPostgresSaver(
            pool, serde=JsonPlusSerializer(allowed_msgpack_modules=None, pickle_fallback=False)
        )
