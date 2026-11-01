"""Shared serialization boundary for every calendar mutation."""

from sqlmodel import Session, select

from app.db.models import User


def lock_calendar(db: Session, user_id: int) -> User:
    return db.exec(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).one()


def changed(db: Session, user: User) -> None:
    user.calendar_revision += 1
    db.add(user)
    db.flush()
