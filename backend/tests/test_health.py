import os

os.environ.setdefault("LIVEKIT_URL", "wss://test.livekit.cloud")
os.environ.setdefault("LIVEKIT_API_KEY", "test-key")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-secret-32chars-minimum-padding")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health_returns_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_token_endpoint_returns_jwt_and_url():
    res = client.post("/token", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["url"].startswith("wss://")
    assert body["room_name"].startswith("tutor-")
    assert body["identity"].startswith("guest-")


def test_token_accepts_custom_room_name():
    res = client.post("/token", json={"room_name": "my-room", "participant_name": "Alice"})
    assert res.status_code == 200
    assert res.json()["room_name"] == "my-room"
