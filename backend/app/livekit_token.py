import os
import uuid
from datetime import timedelta

from livekit import api


def mint_access_token(
    room_name: str,
    identity: str,
    name: str | None = None,
    ttl: timedelta = timedelta(minutes=30),
) -> str:
    api_key = os.environ.get("LIVEKIT_API_KEY", "")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set")

    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_ttl(ttl)
        .with_grants(grants)
    )
    if name:
        token = token.with_name(name)
    return token.to_jwt()


def room_name_for_session(session_id: int) -> str:
    """Encode the Session.id into the LiveKit room name so the agent can
    extract it on dispatch (see `_parse_session_id_from_room` in
    `agent/agent.py` — the parser lives there because it runs in the
    agent process, which can't import from the backend).

    Format: 'tutor-{session_id}-{short_uuid}'. Each call yields a fresh
    room name (uuid suffix), letting us rotate rooms on resume without
    storing room_name in the DB.
    """
    return f"tutor-{session_id}-{uuid.uuid4().hex[:8]}"


def new_participant_identity() -> str:
    return f"guest-{uuid.uuid4().hex[:8]}"
