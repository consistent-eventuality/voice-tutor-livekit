"""SQLite + SQLAlchemy setup for tutor session persistence.

One table: `sessions`. Each row is one attempt at a lesson by a user.
Multiple in-progress sessions per (user_id, lesson_id) are allowed —
clicking Start always inserts a new row; clicking Resume rotates the
room name (which is ephemeral and not stored) but keeps the same row.

Lesson definitions (concepts, titles) live in code in agent/lesson.py.
The DB only references them by lesson_id (string). No catalog table.

The previous schema had a separate user_lessons table as a parent.
That was premature abstraction — no per-(user, lesson) metadata, no
queries that didn't immediately join back to (user_id, lesson_id). All
collapsed onto Session here with denormalized user_id + lesson_id
columns; user_id and lesson_id are immutable after insert so there's
no drift risk.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterator

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    Session as ORMSession,
    declarative_base,
    sessionmaker,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/voice_tutor.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    lesson_id = Column(String, nullable=False)  # references LESSONS in agent/lesson.py
    state_json = Column(Text, nullable=True)    # JSON: {idx, phase, last_gaps}
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


# Most common query: in-progress sessions for a user, ordered by last_active_at desc.
Index("idx_sessions_user_active", Session.user_id, Session.finished_at, Session.last_active_at.desc())


def init_db() -> None:
    """Create the SQLite file (if needed) and tables. Idempotent."""
    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[ORMSession]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
