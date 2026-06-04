from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith("sqlite:///"):
    sqlite_path = Path(DATABASE_URL.replace("sqlite:///", ""))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    import app.db.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

