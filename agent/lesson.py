"""Lesson fixture — an ordered list of concepts the tutor walks through.

Hierarchy:
  Curriculum  =  DAG of Lessons (with prereq edges) — parked future work
  Lesson      =  ordered list of Concepts (this file holds one)
  Concept     =  the loop primitive (TEACH → GRADE → RETEACH? → advance)

This file is intentionally simple — it's data, not engineering. Real product
content would be authored by domain experts. For the take-home, one lesson
of three concepts is enough to demonstrate the loop machinery end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    teach: str   # 2-3 sentence reference content for the agent to read


HTTP_BASICS = Concept(
    id="HTTP_BASICS",
    name="HTTP basics",
    # Short test variant — fast iteration, easy to memorize for testing.
    teach=(
        "HTTP is a stateless request response protocol."
    ),
    # Long content variant — closer to what production curriculum looks like.
    # teach=(
    #     "HTTP is a request-response protocol. A client opens a connection, "
    #     "sends a request, and the server responds — then the connection "
    #     "(conceptually) closes. Each request is independent: the server "
    #     "doesn't remember anything between calls. That statelessness is what "
    #     "makes HTTP scale, but it's also what forces every other protocol "
    #     "we'll discuss to exist."
    # ),
)


WEBSOCKETS = Concept(
    id="WEBSOCKETS",
    name="WebSockets",
    # Short test variant.
    teach=(
        "Websockets use TCP, are bi-directional and great for chat applications"
    ),
    # Long content variant.
    # teach=(
    #     "A WebSocket starts as an HTTP request that asks the server to "
    #     "upgrade the connection. Once upgraded, it's a persistent, "
    #     "bidirectional channel — both sides can send messages whenever, "
    #     "no polling required. It's still TCP underneath, so messages are "
    #     "ordered and reliable. WebSockets are the right tool when you need "
    #     "real-time text-shaped data: chat, presence, live dashboards."
    # ),
)


WEBRTC = Concept(
    id="WEBRTC",
    name="WebRTC",
    # Short test variant.
    teach=(
        "WebRTC is peer-to-peer real-time media and data, optimized for "
        "sub-second latency. It uses UDP."
    ),
    # Long content variant.
    # teach=(
    #     "WebRTC is peer-to-peer real-time media and data, optimized for "
    #     "sub-second latency. It uses UDP-based transport (SRTP for media, "
    #     "SCTP-over-DTLS for data) so a lost packet is dropped rather than "
    #     "retransmitted — that's the right tradeoff for voice and video. "
    #     "It needs a separate signaling channel (often WebSockets) to "
    #     "negotiate the connection, and STUN/TURN servers to traverse NATs."
    # ),
)


# Synthesis is treated as just another concept — it's the integrative
# wrap-up that ties the prior concepts together. Same loop applies:
# agent reads it, asks the recall question, user answers, grader scores.
# Pass → lesson done. Fail → reteach until they get it.
SYNTHESIS = Concept(
    id="SYNTHESIS",
    name="how HTTP, WebSockets, and WebRTC relate",
    teach=(
        "HTTP is request-response and stateless. WebSockets upgrade HTTP "
        "into a persistent bidirectional channel for real-time text. "
        "WebRTC adds peer-to-peer UDP transport for latency-critical media "
        "like voice and video. They form a progression: HTTP for ordinary "
        "request-response, WebSockets when you need server push, WebRTC "
        "when latency and packet-loss tolerance matter more than ordering."
    ),
)


@dataclass(frozen=True)
class Lesson:
    """A unit of curriculum: ordered concepts plus user-facing metadata."""
    id: str
    title: str
    blurb: str          # one-line description for the catalog tile
    concepts: list[Concept]
    closing: str        # spoken when the user passes the last concept


COMMUNICATION_PROTOCOLS = Lesson(
    id="communication_protocols",
    title="Communication Protocols",
    blurb="HTTP, WebSockets, WebRTC — when to use each.",
    concepts=[HTTP_BASICS, WEBSOCKETS, WEBRTC, SYNTHESIS],
    # Spoken when the user passes the last concept — audible signal that
    # the lesson is over before the session disconnects (silence-then-
    # disconnect feels jarring).
    closing="Great work — you've completed the lesson. Goodbye for now.",
)


# ---------- REST API Design ----------


HTTP_VERBS = Concept(
    id="HTTP_VERBS",
    name="HTTP verbs",
    teach=(
        "HTTP verbs convey intent: GET reads, POST creates, PUT replaces, "
        "DELETE removes, PATCH partially updates. Pick the verb that "
        "matches the operation rather than POSTing everything."
    ),
)


STATUS_CODES = Concept(
    id="STATUS_CODES",
    name="HTTP status codes",
    teach=(
        "Status codes signal what happened: 2xx success, 3xx redirect, "
        "4xx client error, 5xx server error. The meaningful ones are 200 "
        "OK, 201 Created, 204 No Content, 401 Unauthorized, 403 Forbidden, "
        "404 Not Found, 422 Unprocessable, and 503 Service Unavailable."
    ),
)


IDEMPOTENCY = Concept(
    id="IDEMPOTENCY",
    name="idempotency",
    teach=(
        "An idempotent operation produces the same result no matter how "
        "many times you call it. GET, PUT, and DELETE are idempotent; "
        "POST is not. Idempotency makes retries safe, which is critical "
        "on unreliable networks."
    ),
)


REST_SYNTHESIS = Concept(
    id="REST_SYNTHESIS",
    name="how verbs, status codes, and idempotency form a REST endpoint",
    teach=(
        "A well-designed REST endpoint combines all three: pick the verb "
        "that matches intent, return the right status code (201 on create, "
        "200 on read, 204 on delete success), and design endpoints to be "
        "idempotent whenever possible so clients can retry safely under "
        "network failure."
    ),
)


REST_API_DESIGN = Lesson(
    id="rest_api_design",
    title="REST API Design",
    blurb="Verbs, status codes, idempotency — anatomy of a well-designed endpoint.",
    concepts=[HTTP_VERBS, STATUS_CODES, IDEMPOTENCY, REST_SYNTHESIS],
    closing="Nice work — you've got the building blocks of REST API design. Goodbye for now.",
)


# Registry of available lessons. Add new Lesson definitions to this dict
# and they'll appear in the catalog automatically.
LESSONS: dict[str, Lesson] = {
    COMMUNICATION_PROTOCOLS.id: COMMUNICATION_PROTOCOLS,
    REST_API_DESIGN.id: REST_API_DESIGN,
}
