"""SQLite + SQLAlchemy setup for tutor lesson + session persistence.

Two tables:
  lessons   — the persistent learning thread (what the user sees in their list)
  sessions  — each individual LiveKit room join under a lesson (children)

A lesson has 1..N sessions. The first session sets the lesson's topic.
Resuming creates a new session under the same lesson and the agent receives
all prior sibling transcripts concatenated.
"""

from __future__ import annotations

import json
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


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    topic = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sessions = relationship(
        "TutorSession",
        back_populates="lesson",
        order_by="TutorSession.started_at",
        cascade="all, delete-orphan",
    )


class TutorSession(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    room_name = Column(String, nullable=False, unique=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    transcript = Column(Text, nullable=True)  # JSON-encoded list[{role, content}]

    lesson = relationship("Lesson", back_populates="sessions")

    def transcript_list(self) -> list[dict]:
        return json.loads(self.transcript) if self.transcript else []


Index("idx_lessons_user_created", Lesson.user_id, Lesson.created_at.desc())
Index("idx_sessions_lesson", TutorSession.lesson_id, TutorSession.started_at)


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


def derive_topic(transcript: list[dict]) -> str:
    """Topic for the list view — first user utterance, truncated."""
    for msg in transcript:
        if msg.get("role") == "user":
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            return (text[:57] + "...") if len(text) > 60 else text
    return "Untitled"
