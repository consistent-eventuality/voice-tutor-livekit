"""LiveKit voice tutor agent worker — state-machine driven.

Per-session orchestration:
  1. On dispatch, fetch session metadata from /sessions/by-room/{room}.
  2. Build a LessonState over the curriculum.
  3. TutorAgent is initialized with the first phase's focused instruction.
  4. After each user turn, on_user_turn_completed hook fires BEFORE the
     agent responds:
       a. Call externalized grader (gpt-4o-mini, JSON schema).
       b. state.transition(grade).
       c. update_instructions to the new phase's prompt.
       d. The realtime model then auto-generates a reply with the new
          instructions.
  5. On shutdown, POST collected transcript to /sessions/end.

Required env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
Optional env: API_BASE_URL (default http://api:8000), GRADER_MODEL,
              OPENAI_REALTIME_MODEL
"""

from __future__ import annotations

import logging
import os

import httpx
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import Agent, AgentSession, ChatContext, JobContext, WorkerOptions, cli
from livekit.agents.llm import ChatMessage
from livekit.plugins import openai as lk_openai

from curriculum import CURRICULUM
from grader import Grader
from state_machine import LessonState

load_dotenv()

logger = logging.getLogger("voice-tutor-agent")
logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")


class TutorAgent(Agent):
    """Agent that runs the structured loop. Hook fires before each agent reply."""

    def __init__(self, state: LessonState, grader: Grader) -> None:
        super().__init__(instructions=state.current_instruction())
        self._state = state
        self._grader = grader

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        if self._state.is_done:
            return

        user_text = (new_message.text_content or "").strip()
        if not user_text:
            return

        concept = self._state.current_concept
        if concept is None:
            return

        try:
            grade = await self._grader.grade(concept, user_text)
            logger.info(
                "Grade: concept=%s score=%d gaps=%s phase_before=%s",
                concept.id, grade.score, grade.gaps, self._state.phase,
            )
            self._state.transition(grade)
            logger.info(
                "Phase after transition: %s (idx=%d)",
                self._state.phase, self._state.idx,
            )
        except Exception as e:
            logger.exception("Grading failed: %s", e)
            return

        if self._state.is_done:
            return

        new_instruction = self._state.current_instruction()
        if not new_instruction:
            return

        await self.update_instructions(new_instruction)
        if self._state.phase == "synthesize":
            # The synthesize turn is the last agent turn; mark done so we
            # don't try to grade further user input.
            self._state.mark_synthesized()


async def _fetch_session_info(room_name: str) -> dict:
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

    await _fetch_session_info(ctx.room.name)

    state = LessonState(curriculum=CURRICULUM)
    grader = Grader()
    agent = TutorAgent(state, grader)

    session = AgentSession(
        llm=lk_openai.realtime.RealtimeModel(
            voice="coral",
            model=os.environ.get("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview"),
        ),
    )

    # Transcript collection for /sessions/end
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

    # Disconnect handling — explicit click ends fast; network drops fall through
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

    await session.start(agent=agent, room=ctx.room)
    # Kick off the first TEACH turn — agent's instructions are already set
    await session.generate_reply()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
