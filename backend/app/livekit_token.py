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
    extract it on dispatch via `parse_session_id_from_room_name`.

    Format: 'tutor-{session_id}-{short_uuid}'. Each call yields a fresh
    room name (uuid suffix), letting us rotate rooms on resume without
    storing room_name in the DB.
    """
    return f"tutor-{session_id}-{uuid.uuid4().hex[:8]}"


def parse_session_id_from_room_name(room_name: str) -> int | None:
    """Extract the Session.id from a room name minted via
    `room_name_for_session`. Returns None on malformed input.
    """
    parts = room_name.split("-")
    if len(parts) >= 3 and parts[0] == "tutor":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def new_participant_identity() -> str:
    return f"guest-{uuid.uuid4().hex[:8]}"
