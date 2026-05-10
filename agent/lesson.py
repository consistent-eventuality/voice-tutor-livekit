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


LESSON: list[Concept] = [HTTP_BASICS, WEBSOCKETS, WEBRTC, SYNTHESIS]


# Spoken when the user passes the last concept — audible signal that the
# lesson is over before the session disconnects (silence-then-disconnect
# feels jarring).
LESSON_CLOSING = (
    "Great work — you've completed the lesson. Goodbye for now."
)
