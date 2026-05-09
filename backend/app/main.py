import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as ORMSession

from app.db import Lesson, TutorSession, derive_topic, get_db, init_db
from app.livekit_token import (
    mint_access_token,
    new_room_name,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")

app = FastAPI(title="voice-tutor-livekit api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    logger.info("DB initialized")


# ---------- /health ----------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------- /token ----------


class TokenRequest(BaseModel):
    user_id: str
    lesson_id: int | None = None  # if set, attach a new session to this lesson
    participant_name: str | None = None


class TokenResponse(BaseModel):
    token: str
    url: str
    room_name: str
    identity: str
    lesson_id: int
    session_id: int
    resuming: bool


@app.post("/token", response_model=TokenResponse)
async def create_token(body: TokenRequest, db: ORMSession = Depends(get_db)) -> TokenResponse:
    if not LIVEKIT_URL:
        raise HTTPException(status_code=503, detail="LIVEKIT_URL not configured")

    if body.lesson_id is not None:
        lesson = (
            db.query(Lesson)
            .filter(Lesson.id == body.lesson_id, Lesson.user_id == body.user_id)
            .first()
        )
        if not lesson:
            raise HTTPException(status_code=404, detail="lesson not found or not owned by user")
        resuming = True
    else:
        lesson = Lesson(user_id=body.user_id)
        db.add(lesson)
        db.flush()  # populate lesson.id
        resuming = False

    room = new_room_name()
    new_session = TutorSession(lesson_id=lesson.id, room_name=room)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    try:
        token = mint_access_token(
            room_name=room,
            identity=body.user_id,
            name=body.participant_name,
        )
    except RuntimeError as e:
        logger.error("Token mint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    return TokenResponse(
        token=token,
        url=LIVEKIT_URL,
        room_name=room,
        identity=body.user_id,
        lesson_id=lesson.id,
        session_id=new_session.id,
        resuming=resuming,
    )


# ---------- /lessons (list) ----------


class LessonListItem(BaseModel):
    id: int
    topic: str
    created_at: datetime
    last_session_at: datetime
    session_count: int


@app.get("/lessons", response_model=list[LessonListItem])
async def list_lessons(user_id: str, db: ORMSession = Depends(get_db)) -> list[LessonListItem]:
    """Lessons that have at least one finished session, newest activity first."""
    rows = (
        db.query(
            Lesson,
            func.max(TutorSession.started_at).label("last_session_at"),
            func.count(TutorSession.id).label("session_count"),
        )
        .join(TutorSession, TutorSession.lesson_id == Lesson.id)
        .filter(
            Lesson.user_id == user_id,
            TutorSession.ended_at.isnot(None),
        )
        .group_by(Lesson.id)
        .order_by(func.max(TutorSession.started_at).desc())
        .all()
    )
    return [
        LessonListItem(
            id=lesson.id,
            topic=lesson.topic or "Untitled",
            created_at=lesson.created_at,
            last_session_at=last_at,
            session_count=count,
        )
        for lesson, last_at, count in rows
    ]


# ---------- /sessions/by-room (agent reads this on dispatch) ----------


class SessionByRoomResponse(BaseModel):
    session_id: int
    lesson_id: int
    user_id: str
    room_name: str
    resume_transcript: list[dict[str, Any]]  # all prior sibling transcripts concat'd


@app.get("/sessions/by-room/{room_name}", response_model=SessionByRoomResponse)
async def get_session_by_room(
    room_name: str, db: ORMSession = Depends(get_db)
) -> SessionByRoomResponse:
    session = db.query(TutorSession).filter(TutorSession.room_name == room_name).first()
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # Concat transcripts from earlier finished sessions in the same lesson
    siblings = (
        db.query(TutorSession)
        .filter(
            TutorSession.lesson_id == session.lesson_id,
            TutorSession.id != session.id,
            TutorSession.ended_at.isnot(None),
        )
        .order_by(TutorSession.started_at)
        .all()
    )
    resume_transcript: list[dict[str, Any]] = []
    for s in siblings:
        resume_transcript.extend(s.transcript_list())

    return SessionByRoomResponse(
        session_id=session.id,
        lesson_id=session.lesson_id,
        user_id=session.lesson.user_id,
        room_name=session.room_name,
        resume_transcript=resume_transcript,
    )


# ---------- /sessions/end (agent posts this on shutdown) ----------


class SessionEndRequest(BaseModel):
    room_name: str
    transcript: list[dict[str, Any]]


class SessionEndResponse(BaseModel):
    status: str
    session_id: int | None = None


@app.post("/sessions/end", response_model=SessionEndResponse)
async def end_session(body: SessionEndRequest, db: ORMSession = Depends(get_db)) -> SessionEndResponse:
    session = db.query(TutorSession).filter(TutorSession.room_name == body.room_name).first()
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    user_msgs = [
        m for m in body.transcript
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    if not user_msgs:
        # Empty session — discard. If this was the only session in the lesson,
        # drop the lesson too so it doesn't appear as a phantom row.
        lesson = session.lesson
        sibling_count = (
            db.query(TutorSession)
            .filter(TutorSession.lesson_id == lesson.id, TutorSession.id != session.id)
            .count()
        )
        db.delete(session)
        if sibling_count == 0:
            db.delete(lesson)
        db.commit()
        return SessionEndResponse(status="discarded")

    session.ended_at = datetime.utcnow()
    session.transcript = json.dumps(body.transcript)
    if session.lesson.topic is None:
        session.lesson.topic = derive_topic(body.transcript)
    db.commit()
    return SessionEndResponse(status="ok", session_id=session.id)
