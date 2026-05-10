"""LiveKit voice tutor agent worker — state-machine driven.

Runs as a separate process. Registers with LiveKit Cloud and gets dispatched
into rooms when users join.

Per-session orchestration:
  1. On dispatch, fetch session metadata from /sessions/by-room/{room}.
  2. Build a LessonState over the curriculum.
  3. Push the first focused TEACH instruction via session.generate_reply.
  4. After each user turn:
       a. Call the externalized grader (gpt-4o-mini, JSON schema).
       b. state.transition(grade) — Python decides next phase.
       c. If not done, push the next focused instruction.
  5. After SYNTHESIZE, mark done. Subsequent user turns are ignored.
  6. On shutdown, POST collected transcript to /sessions/end.

Required env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
Optional env: API_BASE_URL (default http://api:8000), GRADER_MODEL,
              OPENAI_REALTIME_MODEL
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai as lk_openai

from curriculum import CURRICULUM
from grader import Grader
from state_machine import LessonState

load_dotenv()

logger = logging.getLogger("voice-tutor-agent")
logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")

# NOTE: We do NOT use a static system prompt. The persistent system prompt
# is rewritten at every phase boundary via agent.update_instructions(...) so
# the realtime model always sees exactly one focused job — the current
# phase's prompt. The first phase's instructions seed the Agent on init.


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

    # Backend session lookup is harmless even though we're not consuming
    # resume_transcript in the new state-machine design.
    await _fetch_session_info(ctx.room.name)

    state = LessonState(curriculum=CURRICULUM)
    grader = Grader()

    session = AgentSession(
        llm=lk_openai.realtime.RealtimeModel(
            voice="coral",
            model=os.environ.get("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview"),
        ),
    )

    # The agent's persistent system prompt always equals the current phase's
    # focused prompt. We mutate it at every phase boundary via
    # agent.update_instructions(...) so the realtime model has exactly one
    # source of truth at any moment — defeats its training-prior drift.
    agent = Agent(instructions=state.current_instruction())

    # Transcript collection for /sessions/end (unchanged from prior behavior)
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

    # State-machine orchestration: after each user turn, grade + transition + drive next turn
    orchestrator_lock = asyncio.Lock()

    async def _orchestrate(user_text: str) -> None:
        if state.is_done:
            return
        concept = state.current_concept
        if concept is None:
            return

        try:
            grade = await grader.grade(concept, user_text)
            logger.info(
                "Grade: concept=%s score=%d gaps=%s phase_before=%s",
                concept.id, grade.score, grade.gaps, state.phase,
            )
            state.transition(grade)
            logger.info("Phase after transition: %s (idx=%d)", state.phase, state.idx)
        except Exception as e:
            logger.exception("Orchestration error during grading: %s", e)
            return

        if state.phase == "done":
            return

        instruction = state.current_instruction()
        if not instruction:
            return

        try:
            # Replace the persistent system prompt with the new phase's
            # focused instruction, THEN ask the model to generate a reply.
            # update_instructions is authoritative; generate_reply(instructions=)
            # alone gets ignored / merged with priors.
            await agent.update_instructions(instruction)
            await session.generate_reply()
            if state.phase == "synthesize":
                state.mark_synthesized()
        except Exception as e:
            logger.exception("Failed to push next agent turn: %s", e)

    @session.on("user_input_transcribed")
    def _on_user_turn(event) -> None:  # type: ignore[no-untyped-def]
        # Some events fire mid-utterance with is_final=False; skip those.
        if getattr(event, "is_final", True) is False:
            return
        text = (getattr(event, "transcript", "") or "").strip()
        if not text:
            return
        # Schedule async orchestration — the event handler itself must return quickly.
        asyncio.create_task(_orchestrate_safe(text))

    async def _orchestrate_safe(user_text: str) -> None:
        async with orchestrator_lock:
            await _orchestrate(user_text)

    # Disconnect handling — explicit click ends fast; network drops fall through to empty_timeout
    shutdown_started = False

    @ctx.room.on("participant_disconnected")
    def _on_user_left(participant: rtc.RemoteParticipant) -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        reason = getattr(participant, "disconnect_reason", None)
        if reason != rtc.DisconnectReason.CLIENT_INITIATED:
            logger.info(
                "Participant %s dropped (reason=%s) — waiting for empty_timeout",
                participant.identity, reason,
            )
            return
        shutdown_started = True
        logger.info(
            "Participant %s explicitly disconnected — shutting down job",
            participant.identity,
        )
        ctx.shutdown(reason="user_disconnected")

    async def _on_shutdown() -> None:
        await _post_session_end(ctx.room.name, collected)

    ctx.add_shutdown_callback(_on_shutdown)

    # Boot the session — agent already initialized with first phase's prompt
    await session.start(agent=agent, room=ctx.room)
    # Kick off the first TEACH turn (system prompt is already correct)
    await session.generate_reply()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
