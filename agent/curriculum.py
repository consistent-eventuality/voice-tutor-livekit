"""Curriculum fixture for the structured tutoring loop.

This file is intentionally simple — it's data, not engineering. Real product
content would be authored by domain experts, run through editorial review,
and possibly driven from a CMS. For the take-home, three concepts are enough
to demonstrate the loop machinery end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RubricItem:
    description: str       # what the agent should look for in the user's answer
    ideal_answer: str      # short phrase capturing what "nailed" looks like


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    teach: str             # 2-3 sentence reference content for the agent to read
    recall_prompt: str     # how the agent invites the user to demonstrate understanding
    rubric: list[RubricItem]


HTTP_BASICS = Concept(
    id="HTTP_BASICS",
    name="HTTP basics",
    teach=(
        "HTTP is a request-response protocol. A client opens a connection, "
        "sends a request, and the server responds — then the connection "
        "(conceptually) closes. Each request is independent: the server "
        "doesn't remember anything between calls. That statelessness is what "
        "makes HTTP scale, but it's also what forces every other protocol "
        "we'll discuss to exist."
    ),
    recall_prompt="What's your understanding of HTTP?",
    rubric=[
        RubricItem(
            description="Identifies a clean request-response use case",
            ideal_answer="loading a webpage, fetching data on demand, REST APIs",
        ),
        RubricItem(
            description="Identifies a real-time / push limitation",
            ideal_answer="needs polling for updates, server can't push to client",
        ),
        RubricItem(
            description="Mentions statelessness as a feature and/or a constraint",
            ideal_answer="scales because each request is independent; but session "
            "state needs cookies/tokens to fake continuity",
        ),
    ],
)


WEBSOCKETS = Concept(
    id="WEBSOCKETS",
    name="WebSockets",
    teach=(
        "A WebSocket starts as an HTTP request that asks the server to "
        "upgrade the connection. Once upgraded, it's a persistent, "
        "bidirectional channel — both sides can send messages whenever, "
        "no polling required. It's still TCP underneath, so messages are "
        "ordered and reliable. WebSockets are the right tool when you need "
        "real-time text-shaped data: chat, presence, live dashboards."
    ),
    recall_prompt="What's your understanding of WebSockets?",
    rubric=[
        RubricItem(
            description="Names bidirectional + persistent connection as the key win",
            ideal_answer="server can push without the client asking; one connection lasts the session",
        ),
        RubricItem(
            description="Articulates concrete benefit over polling",
            ideal_answer="lower latency and less request overhead than re-polling every N seconds",
        ),
        RubricItem(
            description="Identifies a case where WebSockets are the wrong fit",
            ideal_answer="real-time audio/video (TCP head-of-line blocking is fatal); "
            "or one-shot request-response where it's just overkill",
        ),
    ],
)


WEBRTC = Concept(
    id="WEBRTC",
    name="WebRTC",
    teach=(
        "WebRTC is peer-to-peer real-time media and data, optimized for "
        "sub-second latency. It uses UDP-based transport (SRTP for media, "
        "SCTP-over-DTLS for data) so a lost packet is dropped rather than "
        "retransmitted — that's the right tradeoff for voice and video. "
        "It needs a separate signaling channel (often WebSockets) to "
        "negotiate the connection, and STUN/TURN servers to traverse NATs."
    ),
    recall_prompt="What's your understanding of WebRTC?",
    rubric=[
        RubricItem(
            description="Identifies UDP vs TCP and the packet-loss tradeoff",
            ideal_answer="UDP drops lost packets (codec interpolates) instead of stalling on retransmit; "
            "TCP head-of-line blocking would cause audible glitches",
        ),
        RubricItem(
            description="Names peer-to-peer and/or NAT traversal as a structural difference",
            ideal_answer="media flows directly between peers (or through an SFU), not through your app server; "
            "STUN/TURN handle NAT",
        ),
        RubricItem(
            description="Recognizes WebRTC needs WebSockets (or equivalent) for signaling — they're not substitutes",
            ideal_answer="WebSockets handle signaling (offer/answer, ICE), WebRTC handles media — different layers, complementary",
        ),
        RubricItem(
            description="Connects the choice to the voice/media use case",
            ideal_answer="real-time voice needs low latency + drop tolerance, which only UDP-based WebRTC gives you",
        ),
    ],
)


CURRICULUM: list[Concept] = [HTTP_BASICS, WEBSOCKETS, WEBRTC]
