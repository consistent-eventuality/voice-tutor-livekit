"""LiveKit voice tutor agent worker.

Runs as a separate process. Registers with LiveKit Cloud and gets dispatched
into rooms when users join. One agent process can serve multiple concurrent
sessions; scale horizontally by running more processes (k8s/ECS).

On dispatch the agent:
  1. Calls the API at /sessions/by-room/{room} to fetch session metadata
     (including any prior transcript if the user clicked Resume).
  2. Seeds its instructions with the prior transcript when present.
  3. Collects new transcript items via conversation_item_added events.
  4. POSTs the full transcript to /sessions/end on shutdown.

Run locally:
    python agent.py dev      # hot-reload, attaches to LiveKit Cloud
    python agent.py start    # production worker

Required env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
Optional env: API_BASE_URL (default http://api:8000)
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai

load_dotenv()

logger = logging.getLogger("voice-tutor-agent")
logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")

TUTOR_INSTRUCTIONS = (
    "You are a friendly, patient voice tutor. "
    "Always respond in English unless the user explicitly asks you to switch "
    "languages. "
    "Greet the user warmly and ask what they'd like to learn about today. "
    "Once they pick a topic, teach in short, conversational turns: explain a "
    "concept in 2-3 sentences, then ask a check-in question to make sure they "
    "follow. Keep your tone encouraging. The subject is open-ended for now."
)


def _format_resume_block(transcript: list[dict]) -> str:
    """Render prior turns as a transcript block to seed the agent's context."""
    lines = []
    for msg in transcript:
        role = msg.get("role", "?")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        speaker = "User" if role == "user" else "Tutor"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


async def _fetch_session_info(room_name: str) -> dict:
    """Look up the session row created at /token time. Returns {} on failure."""
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5.0) as http:
            res = await http.get(f"/sessions/by-room/{room_name}")
            res.raise_for_status()
            return res.json()
    except Exception as e:
        logger.warning("Couldn't fetch session info from API: %s", e)
        return {}


async def _post_session_end(room_name: str, transcript: list[dict]) -> None:
    if not transcript:
        logger.info("No transcript to persist for room %s", room_name)
        return
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as http:
            res = await http.post(
                "/sessions/end",
                json={"room_name": room_name, "transcript": transcript},
            )
            res.raise_for_status()
            logger.info("Persisted session for room %s: %s", room_name, res.json())
    except Exception as e:
        logger.warning("Failed to persist session end: %s", e)


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Agent dispatched to room: %s", ctx.room.name)
    await ctx.connect()

    info = await _fetch_session_info(ctx.room.name)
    resume_transcript = info.get("resume_transcript") or []

    instructions = TUTOR_INSTRUCTIONS
    if resume_transcript:
        prior = _format_resume_block(resume_transcript)
        instructions += (
            "\n\nThe user is resuming a prior session. Here is what was said "
            "last time, in order:\n---\n"
            f"{prior}\n---\n"
            "Greet them by acknowledging you're picking up where you left off, "
            "briefly recap the topic in one sentence, and continue teaching. "
            "Don't repeat content verbatim."
        )
        logger.info("Resuming with %d prior turns", len(resume_transcript))

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="coral",
            model=os.environ.get("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview"),
        ),
    )

    # Pipelined alternative (uncomment + add plugins to requirements.txt):
    #
    # from livekit.plugins import deepgram, cartesia, silero
    # session = AgentSession(
    #     vad=silero.VAD.load(),
    #     stt=deepgram.STT(model="nova-3"),
    #     llm=openai.LLM(model="gpt-4o-mini"),
    #     tts=cartesia.TTS(model="sonic-2"),
    # )

    collected: list[dict] = []

    @session.on("conversation_item_added")
    def _on_item(event) -> None:  # type: ignore[no-untyped-def]
        item = event.item
        role = getattr(item, "role", None)
        if role not in ("user", "assistant"):
            return
        content = getattr(item, "text_content", None)
        if content is None and hasattr(item, "content"):
            raw = item.content
            content = raw if isinstance(raw, str) else " ".join(str(c) for c in raw)
        content = (content or "").strip()
        if content:
            collected.append({"role": role, "content": content})

    # End the job immediately when the user disconnects. Without this, the
    # agent waits for LiveKit's empty_timeout (default ~20s) before its
    # shutdown callback fires, which delays the lesson appearing in the
    # past-lessons list.
    shutdown_started = False

    @ctx.room.on("participant_disconnected")
    def _on_user_left(participant) -> None:  # type: ignore[no-untyped-def]
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        logger.info("Participant %s left — closing session", participant.identity)
        asyncio.create_task(session.aclose())

    async def _on_shutdown() -> None:
        await _post_session_end(ctx.room.name, collected)

    ctx.add_shutdown_callback(_on_shutdown)

    await session.start(agent=Agent(instructions=instructions), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
