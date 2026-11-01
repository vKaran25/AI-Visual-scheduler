"""Release command: python -m app.db.migrate."""

import os

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver

from app.core.config import BASE_DIR, DATABASE_DIRECT_URL, raw_postgres_url


def main():
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    command.upgrade(Config(str(BASE_DIR / "alembic.ini")), "head")
    with PostgresSaver.from_conn_string(raw_postgres_url(DATABASE_DIRECT_URL)) as saver:
        saver.setup()
    print("Application and checkpoint schemas are up to date.")


if __name__ == "__main__":
    main()
