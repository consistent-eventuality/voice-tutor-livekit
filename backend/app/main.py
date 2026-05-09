import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.livekit_token import (
    mint_access_token,
    new_participant_identity,
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


class TokenRequest(BaseModel):
    room_name: str | None = None
    participant_name: str | None = None


class TokenResponse(BaseModel):
    token: str
    url: str
    room_name: str
    identity: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/token", response_model=TokenResponse)
async def create_token(body: TokenRequest | None = None) -> TokenResponse:
    if not LIVEKIT_URL:
        raise HTTPException(status_code=503, detail="LIVEKIT_URL not configured")

    body = body or TokenRequest()
    room = body.room_name or new_room_name()
    identity = new_participant_identity()

    try:
        token = mint_access_token(
            room_name=room,
            identity=identity,
            name=body.participant_name,
        )
    except RuntimeError as e:
        logger.error("Token mint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    return TokenResponse(token=token, url=LIVEKIT_URL, room_name=room, identity=identity)
