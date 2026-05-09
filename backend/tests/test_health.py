import os
import tempfile

# Configure test env BEFORE importing the app
os.environ.setdefault("LIVEKIT_URL", "wss://test.livekit.cloud")
os.environ.setdefault("LIVEKIT_API_KEY", "test-key")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-secret-32chars-minimum-padding")

# Use a temp SQLite file per test run so tests don't pollute local data
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

USER_ID = "test-user-uuid"


def test_health_returns_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_token_creates_new_lesson_and_session():
    res = client.post("/token", json={"user_id": USER_ID})
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["url"].startswith("wss://")
    assert body["room_name"].startswith("tutor-")
    assert body["identity"] == USER_ID
    assert body["lesson_id"] > 0
    assert body["session_id"] > 0
    assert body["resuming"] is False


def test_lessons_list_filters_to_finished_sessions():
    # Initial state — empty list
    res = client.get(f"/lessons?user_id={USER_ID}")
    initial_count = len(res.json())

    # New session with no transcript → discarded → no lesson appears
    token_res = client.post("/token", json={"user_id": USER_ID}).json()
    end_res = client.post(
        "/sessions/end",
        json={"room_name": token_res["room_name"], "transcript": []},
    )
    assert end_res.json()["status"] == "discarded"

    res = client.get(f"/lessons?user_id={USER_ID}")
    assert len(res.json()) == initial_count

    # Session with real transcript → lesson appears
    token_res = client.post("/token", json={"user_id": USER_ID}).json()
    end_res = client.post(
        "/sessions/end",
        json={
            "room_name": token_res["room_name"],
            "transcript": [
                {"role": "assistant", "content": "Hi, what would you like to learn?"},
                {"role": "user", "content": "Teach me chess openings please"},
                {"role": "assistant", "content": "Great choice. Let's start..."},
            ],
        },
    ).json()
    assert end_res["status"] == "ok"

    res = client.get(f"/lessons?user_id={USER_ID}")
    body = res.json()
    assert len(body) == initial_count + 1
    latest = body[0]
    assert "chess openings" in latest["topic"].lower()
    assert latest["session_count"] == 1


def test_resume_creates_new_session_under_existing_lesson():
    # Create a lesson with one finished session
    t1 = client.post("/token", json={"user_id": USER_ID}).json()
    client.post(
        "/sessions/end",
        json={
            "room_name": t1["room_name"],
            "transcript": [
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "Tell me about jazz piano"},
            ],
        },
    )
    lesson_id = t1["lesson_id"]

    # Resume — passes lesson_id, expects resuming=true
    t2 = client.post("/token", json={"user_id": USER_ID, "lesson_id": lesson_id}).json()
    assert t2["lesson_id"] == lesson_id
    assert t2["resuming"] is True
    assert t2["session_id"] != t1["session_id"]
    assert t2["room_name"] != t1["room_name"]


def test_session_by_room_returns_concatenated_prior_transcripts():
    # Lesson with two finished sessions
    t1 = client.post("/token", json={"user_id": USER_ID}).json()
    client.post(
        "/sessions/end",
        json={
            "room_name": t1["room_name"],
            "transcript": [
                {"role": "user", "content": "First session question"},
                {"role": "assistant", "content": "First session answer"},
            ],
        },
    )
    lesson_id = t1["lesson_id"]

    t2 = client.post("/token", json={"user_id": USER_ID, "lesson_id": lesson_id}).json()
    client.post(
        "/sessions/end",
        json={
            "room_name": t2["room_name"],
            "transcript": [
                {"role": "user", "content": "Second session question"},
                {"role": "assistant", "content": "Second session answer"},
            ],
        },
    )

    # Open a third session — agent should see both prior transcripts
    t3 = client.post("/token", json={"user_id": USER_ID, "lesson_id": lesson_id}).json()
    res = client.get(f"/sessions/by-room/{t3['room_name']}")
    body = res.json()
    transcript = body["resume_transcript"]
    assert len(transcript) == 4
    assert transcript[0]["content"] == "First session question"
    assert transcript[2]["content"] == "Second session question"


def test_resume_rejects_other_users_lesson():
    other_user = "different-user"
    t1 = client.post("/token", json={"user_id": USER_ID}).json()
    client.post(
        "/sessions/end",
        json={
            "room_name": t1["room_name"],
            "transcript": [
                {"role": "user", "content": "Mine"},
            ],
        },
    )

    res = client.post(
        "/token", json={"user_id": other_user, "lesson_id": t1["lesson_id"]}
    )
    assert res.status_code == 404
