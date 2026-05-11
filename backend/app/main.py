import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session as ORMSession

from app.db import Session, get_db, init_db
from app.lesson_catalog import LESSON_CATALOG, concept_count, current_concept_name
from app.livekit_token import (
    mint_access_token,
    new_participant_identity,
    room_name_for_session,
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


# ---------- /lessons (catalog) ----------


class LessonCatalogItem(BaseModel):
    id: str
    title: str
    blurb: str
    concept_count: int


@app.get("/lessons", response_model=list[LessonCatalogItem])
async def list_lessons() -> list[LessonCatalogItem]:
    """Return the catalog of available lessons. Static — sourced from
    backend/app/lesson_catalog.py which mirrors the agent's LESSONS dict."""
    return [
        LessonCatalogItem(
            id=lid,
            title=meta["title"],
            blurb=meta["blurb"],
            concept_count=concept_count(lid),
        )
        for lid, meta in LESSON_CATALOG.items()
    ]


# ---------- /sessions (in-progress for a user) ----------


class InProgressSession(BaseModel):
    session_id: int
    lesson_id: str
    lesson_title: str
    concept_count: int
    idx: int
    phase: str
    current_concept_name: str | None
    started_at: datetime
    last_active_at: datetime


@app.get("/sessions", response_model=list[InProgressSession])
async def list_in_progress_sessions(
    user_id: str, db: ORMSession = Depends(get_db)
) -> list[InProgressSession]:
    """All in-progress (finished_at IS NULL) sessions for a user, ordered
    most-recent-active first. Each entry becomes a Continue tile in the UI."""
    rows = (
        db.query(Session)
        .filter(
            Session.user_id == user_id,
            Session.finished_at.is_(None),
        )
        .order_by(desc(Session.last_active_at))
        .all()
    )
    out = []
    for sess in rows:
        meta = LESSON_CATALOG.get(sess.lesson_id, {})
        state = json.loads(sess.state_json) if sess.state_json else {}
        idx = int(state.get("idx", 0))
        out.append(
            InProgressSession(
                session_id=sess.id,
                lesson_id=sess.lesson_id,
                lesson_title=meta.get("title", sess.lesson_id),
                concept_count=concept_count(sess.lesson_id),
                idx=idx,
                phase=str(state.get("phase", "teach")),
                current_concept_name=current_concept_name(sess.lesson_id, idx),
                started_at=sess.started_at,
                last_active_at=sess.last_active_at,
            )
        )
    return out


# ---------- POST /sessions (create or resume) ----------


class SessionRequest(BaseModel):
    user_id: str
    lesson_id: str | None = None
    session_id: int | None = None
    participant_name: str | None = None


class SessionResponse(BaseModel):
    token: str
    url: str
    room_name: str
    identity: str
    session_id: int
    lesson_id: str
    resuming: bool


@app.post("/sessions", response_model=SessionResponse)
async def create_or_resume_session(
    body: SessionRequest, db: ORMSession = Depends(get_db)
) -> SessionResponse:
    """Create or resume a Session and return a LiveKit access token.

    - If `session_id` is provided: resume that specific session. Mint a
      new room_name (rotated each resume), don't touch state_json.
    - Otherwise: start fresh. Insert a new Session with the given
      lesson_id. Other in-progress sessions for the same (user, lesson)
      are left alone (multiple concurrent attempts are allowed).
    """
    if not LIVEKIT_URL:
        raise HTTPException(status_code=503, detail="LIVEKIT_URL not configured")

    if body.session_id is not None:
        # Resume specific session
        sess = (
            db.query(Session)
            .filter(
                Session.id == body.session_id,
                Session.user_id == body.user_id,
            )
            .first()
        )
        if not sess:
            raise HTTPException(
                status_code=404,
                detail="session not found or not owned by user",
            )
        if sess.finished_at is not None:
            raise HTTPException(
                status_code=409, detail="session is already finished"
            )
        sess.last_active_at = datetime.utcnow()
        db.commit()
        lesson_id = sess.lesson_id
        session_id = sess.id
        resuming = True
    else:
        # Fresh start (Available tile)
        if not body.lesson_id:
            raise HTTPException(
                status_code=400,
                detail="lesson_id required when session_id is omitted",
            )
        if body.lesson_id not in LESSON_CATALOG:
            raise HTTPException(
                status_code=404, detail=f"unknown lesson_id: {body.lesson_id}"
            )

        new_session = Session(
            user_id=body.user_id,
            lesson_id=body.lesson_id,
            state_json=json.dumps(
                {"idx": 0, "phase": "teach", "last_gaps": []}
            ),
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)

        lesson_id = body.lesson_id
        session_id = new_session.id
        resuming = False

    room = room_name_for_session(session_id)
    identity = body.user_id
    try:
        token = mint_access_token(
            room_name=room, identity=identity, name=body.participant_name
        )
    except RuntimeError as e:
        logger.error("Token mint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    return SessionResponse(
        token=token,
        url=LIVEKIT_URL,
        room_name=room,
        identity=identity,
        session_id=session_id,
        lesson_id=lesson_id,
        resuming=resuming,
    )


# ---------- /sessions/{id} (agent reads on dispatch) ----------


class SessionInfoResponse(BaseModel):
    session_id: int
    lesson_id: str
    state_json: dict[str, Any]


@app.get("/sessions/{session_id}", response_model=SessionInfoResponse)
async def get_session(
    session_id: int, db: ORMSession = Depends(get_db)
) -> SessionInfoResponse:
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    state = json.loads(sess.state_json) if sess.state_json else {
        "idx": 0,
        "phase": "teach",
        "last_gaps": [],
    }
    return SessionInfoResponse(
        session_id=sess.id,
        lesson_id=sess.lesson_id,
        state_json=state,
    )


# ---------- /sessions/{id}/state (agent PUTs on every transition) ----------


class StateUpdateRequest(BaseModel):
    state_json: dict[str, Any]


class StateUpdateResponse(BaseModel):
    status: str


@app.put("/sessions/{session_id}/state", response_model=StateUpdateResponse)
async def update_session_state(
    session_id: int,
    body: StateUpdateRequest,
    db: ORMSession = Depends(get_db),
) -> StateUpdateResponse:
    sess = db.query(Session).filter(Session.id == session_id).first()
    if not sess:
        # Orphan — might be a stale agent worker against a wiped DB.
        # Best-effort, don't surface a noisy error to the agent.
        logger.warning("orphan state update for session_id=%d", session_id)
        return StateUpdateResponse(status="orphan")

    sess.state_json = json.dumps(body.state_json)
    sess.last_active_at = datetime.utcnow()
    if body.state_json.get("phase") == "done":
        sess.finished_at = datetime.utcnow()
    db.commit()
    return StateUpdateResponse(status="ok")
