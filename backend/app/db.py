"""SQLite + SQLAlchemy setup for tutor lesson + session persistence.

Two tables:
  user_lessons — one row per (user, lesson_id). The user's stable record
                 of having engaged with a lesson. Holds nothing about
                 progress directly — that lives on Sessions.
  sessions     — one row per attempt. Multiple attempts per UserLesson
                 are allowed; each is independent. Holds the serialized
                 LessonState for resumability.

Lesson definitions (concepts, titles, blurbs) live in code in agent/lesson.py.
The DB only references them by lesson_id (string). No catalog table.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterator

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    Session as ORMSession,
    declarative_base,
    relationship,
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


class UserLesson(Base):
    __tablename__ = "user_lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    lesson_id = Column(String, nullable=False)  # references LESSONS in agent/lesson.py
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sessions = relationship(
        "Session",
        back_populates="user_lesson",
        order_by="Session.started_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_user_lesson"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_lesson_id = Column(
        Integer, ForeignKey("user_lessons.id"), nullable=False
    )
    state_json = Column(Text, nullable=True)  # JSON: {idx, phase, last_gaps}
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    user_lesson = relationship("UserLesson", back_populates="sessions")


Index("idx_user_lessons_user", UserLesson.user_id)
Index("idx_sessions_lesson_active", Session.user_lesson_id, Session.last_active_at.desc())


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
