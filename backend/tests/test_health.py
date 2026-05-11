"""Smoke + integration tests for the FastAPI surface.

Covers /health, /lessons (catalog), POST /sessions (create + resume),
GET /sessions (list), GET /sessions/{id} (agent lookup), PUT
/sessions/{id}/state, and the cross-user / finished-session guard rails.

Uses a temp SQLite file per test run so tests don't pollute local data.
"""

import os
import tempfile

# Configure test env BEFORE importing the app
os.environ.setdefault("LIVEKIT_URL", "wss://test.livekit.cloud")
os.environ.setdefault("LIVEKIT_API_KEY", "test-key")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-secret-32chars-minimum-padding")

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

USER_ID = "test-user-uuid"
LESSON_ID = "communication_protocols"


# ---------- /health ----------


def test_health_returns_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ---------- /lessons (catalog) ----------


def test_lessons_catalog_returns_communication_protocols():
    res = client.get("/lessons")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    by_id = {l["id"]: l for l in body}
    assert LESSON_ID in by_id
    lesson = by_id[LESSON_ID]
    assert lesson["title"] == "Communication Protocols"
    assert lesson["concept_count"] == 4
    assert "blurb" in lesson and lesson["blurb"]


# ---------- POST /sessions (start fresh) ----------


def test_create_session_starts_fresh_lesson():
    res = client.post(
        "/sessions",
        json={"user_id": USER_ID, "lesson_id": LESSON_ID},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["url"].startswith("wss://")
    assert body["lesson_id"] == LESSON_ID
    assert body["session_id"] > 0
    assert body["identity"] == USER_ID
    assert body["resuming"] is False


def test_create_session_room_name_encodes_session_id():
    body = client.post(
        "/sessions",
        json={"user_id": USER_ID, "lesson_id": LESSON_ID},
    ).json()
    parts = body["room_name"].split("-")
    assert parts[0] == "tutor"
    assert int(parts[1]) == body["session_id"]


def test_create_session_rejects_unknown_lesson_id():
    res = client.post(
        "/sessions",
        json={"user_id": USER_ID, "lesson_id": "nope_does_not_exist"},
    )
    assert res.status_code == 404


def test_create_session_requires_lesson_id_or_session_id():
    res = client.post("/sessions", json={"user_id": USER_ID})
    assert res.status_code == 400


# ---------- /sessions list (in-progress) ----------


def test_in_progress_sessions_listed_with_concept_name():
    user = "list-test-user"
    client.post("/sessions", json={"user_id": user, "lesson_id": LESSON_ID})

    res = client.get(f"/sessions?user_id={user}")
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1
    item = body[0]
    assert item["lesson_id"] == LESSON_ID
    assert item["lesson_title"] == "Communication Protocols"
    assert item["concept_count"] == 4
    assert item["idx"] == 0
    assert item["phase"] == "teach"
    assert item["current_concept_name"] == "HTTP basics"


def test_in_progress_sessions_excludes_finished():
    user = "finished-test-user"
    token = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()
    sid = token["session_id"]

    # Mark the session done via a state save
    client.put(
        f"/sessions/{sid}/state",
        json={"state_json": {"idx": 4, "phase": "done", "last_gaps": []}},
    )

    res = client.get(f"/sessions?user_id={user}")
    assert res.status_code == 200
    assert len(res.json()) == 0


# ---------- GET /sessions/{id} (agent's lookup) ----------


def test_session_lookup_returns_state_and_lesson():
    token = client.post(
        "/sessions", json={"user_id": USER_ID, "lesson_id": LESSON_ID}
    ).json()
    sid = token["session_id"]

    res = client.get(f"/sessions/{sid}")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == sid
    assert body["lesson_id"] == LESSON_ID
    assert body["state_json"]["idx"] == 0
    assert body["state_json"]["phase"] == "teach"


def test_session_lookup_404_for_unknown_id():
    res = client.get("/sessions/99999")
    assert res.status_code == 404


# ---------- PUT /sessions/{id}/state ----------


def test_state_save_persists_and_lookup_reads_back():
    token = client.post(
        "/sessions", json={"user_id": USER_ID, "lesson_id": LESSON_ID}
    ).json()
    sid = token["session_id"]

    new_state = {"idx": 2, "phase": "reteach", "last_gaps": ["didn't mention NAT"]}
    res = client.put(f"/sessions/{sid}/state", json={"state_json": new_state})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Lookup should return what we just saved
    body = client.get(f"/sessions/{sid}").json()
    assert body["state_json"] == new_state


def test_state_save_done_marks_finished_and_drops_from_list():
    user = "done-test-user"
    token = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()
    sid = token["session_id"]

    client.put(
        f"/sessions/{sid}/state",
        json={"state_json": {"idx": 4, "phase": "done", "last_gaps": []}},
    )

    # Should no longer appear in /sessions for this user
    body = client.get(f"/sessions?user_id={user}").json()
    assert all(s["session_id"] != sid for s in body)


def test_state_save_orphan_returns_200_not_404():
    res = client.put(
        "/sessions/99999/state",
        json={"state_json": {"idx": 0, "phase": "teach", "last_gaps": []}},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "orphan"


# ---------- POST /sessions (resume) ----------


def test_resume_session_rotates_room_name_keeps_session_id():
    user = "resume-test-user"
    t1 = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()

    t2 = client.post(
        "/sessions", json={"user_id": user, "session_id": t1["session_id"]}
    ).json()
    assert t2["session_id"] == t1["session_id"]
    assert t2["room_name"] != t1["room_name"]
    assert t2["resuming"] is True
    assert t2["lesson_id"] == LESSON_ID


def test_resume_rejects_other_users_session():
    t1 = client.post(
        "/sessions", json={"user_id": "owner", "lesson_id": LESSON_ID}
    ).json()
    res = client.post(
        "/sessions", json={"user_id": "intruder", "session_id": t1["session_id"]}
    )
    assert res.status_code == 404


def test_resume_rejects_finished_session():
    user = "finished-resume-user"
    t1 = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()
    client.put(
        f"/sessions/{t1['session_id']}/state",
        json={"state_json": {"idx": 4, "phase": "done", "last_gaps": []}},
    )

    res = client.post(
        "/sessions", json={"user_id": user, "session_id": t1["session_id"]}
    )
    assert res.status_code == 409


# ---------- Multi-attempt invariants ----------


def test_multiple_in_progress_sessions_allowed_per_user_and_lesson():
    user = "multi-attempt-user"
    t1 = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()
    t2 = client.post(
        "/sessions", json={"user_id": user, "lesson_id": LESSON_ID}
    ).json()

    # Two distinct sessions, both in-progress, both visible in Continue
    assert t1["session_id"] != t2["session_id"]
    body = client.get(f"/sessions?user_id={user}").json()
    ids = {s["session_id"] for s in body}
    assert {t1["session_id"], t2["session_id"]} <= ids


def test_repeated_starts_create_distinct_sessions_same_lesson_id():
    """Two Starts on the same lesson insert two separate Session rows,
    both tagged with the same lesson_id."""
    user = "repeat-starts-user"
    client.post("/sessions", json={"user_id": user, "lesson_id": LESSON_ID})
    client.post("/sessions", json={"user_id": user, "lesson_id": LESSON_ID})

    body = client.get(f"/sessions?user_id={user}").json()
    assert all(s["lesson_id"] == LESSON_ID for s in body)
    assert len(body) == 2
