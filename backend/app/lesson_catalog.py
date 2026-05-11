"""Backend-side mirror of agent/lesson.py LESSONS metadata.

For a production system this would be in a database. This is static content. 

The agent owns the actual lesson content (concepts + teach text). The
backend only needs the *shape* of each lesson — title, blurb, and how
many concepts it has — so it can serve `GET /lessons` and compute
progress (idx/total) for the Continue tiles.

This is intentionally duplicated rather than imported: the agent runs in
its own container and sharing modules across services means PYTHONPATH
hacks. Adding a new lesson means updating this dict AND the agent's
LESSONS registry. Two small edits are cheaper than the alternative.
"""

LESSON_CATALOG: dict[str, dict] = {
    "communication_protocols": {
        "title": "Communication Protocols",
        "blurb": "HTTP, WebSockets, WebRTC — when to use each.",
        "concept_names": [
            "HTTP basics",
            "WebSockets",
            "WebRTC",
            "how HTTP, WebSockets, and WebRTC relate",
        ],
    },
    "rest_api_design": {
        "title": "REST API Design",
        "blurb": "Verbs, status codes, idempotency — anatomy of a well-designed endpoint.",
        "concept_names": [
            "HTTP verbs",
            "HTTP status codes",
            "idempotency",
            "how verbs, status codes, and idempotency form a REST endpoint",
        ],
    },
}


def concept_count(lesson_id: str) -> int:
    return len(LESSON_CATALOG.get(lesson_id, {}).get("concept_names", []))


def current_concept_name(lesson_id: str, idx: int) -> str | None:
    """Return the human-readable name of the concept at `idx` for the
    given lesson, or None if idx is out of bounds (e.g. lesson is done).
    """
    names = LESSON_CATALOG.get(lesson_id, {}).get("concept_names", [])
    if 0 <= idx < len(names):
        return names[idx]
    return None
