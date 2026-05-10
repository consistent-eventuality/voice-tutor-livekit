"""LiveKit voice tutor agent worker — state-machine driven, static content.

Per-session orchestration:
  1. On dispatch, parse session_id from ctx.room.name (encoded by backend
     as `tutor-{session_id}-{uuid}`).
  2. GET /sessions/{session_id} for {lesson_id, state_json}.
  3. Look up Lesson in agent's LESSONS registry by lesson_id.
  4. Hydrate LessonState from state_json (or fresh if state is empty).
  5. Speak the current phase's text via session.say().
  6. After each user turn, on_user_turn_completed fires:
       a. Cheat phrase → synthetic pass.
       b. Otherwise: gpt-4o-mini grader → {score, gaps}.
       c. state.transition(grade) — Python branch decides next phase.
       d. POST /sessions/{id}/state with new state_json.
       e. session.say(text) for the next phase's curated content.

Per-transition state save lets the user disconnect mid-lesson (clean OR
crash) and resume from the same concept on a different attempt.

The only LLM call in the per-turn loop is the grader. All agent voice
output goes through session.say() which bypasses the LLM and feeds TTS
directly. AgentSession's LLM is required by the framework but never
invoked for content generation; StopResponse on every hook exit suppresses
the framework's auto-reply.

Required env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
Optional env: API_BASE_URL (default http://api:8000), GRADER_MODEL
"""

from __future__ import annotations

import logging
import os

import httpx
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, StopResponse, WorkerOptions, cli
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.plugins import openai as lk_openai, silero

import prompts
from lesson import LESSONS, Lesson
from grader import Grader
from state_machine import Grade, LessonState

load_dotenv()

logger = logging.getLogger("voice-tutor-agent")
logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")

# Cheat phrase — say this instead of a real answer to advance the state
# machine without calling the grader. Designed for fast end-to-end testing
# (walk a lesson from start to finish without thoughtful answers).
# Configurable via env if you want something different.
CHEAT_PHRASE = os.environ.get("VOICE_TUTOR_CHEAT", "abracadabra").strip().lower()


def _is_cheat_phrase(user_text: str) -> bool:
    cleaned = user_text.strip().rstrip(".!?,;:").strip().lower()
    return cleaned == CHEAT_PHRASE


def _parse_session_id_from_room(room_name: str) -> int | None:
    """Extract session id from room name minted as `tutor-{id}-{uuid}`."""
    parts = room_name.split("-")
    if len(parts) >= 3 and parts[0] == "tutor":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


class TutorAgent(Agent):
    """Agent that runs the structured loop. Hook fires before each agent reply."""

    def __init__(
        self,
        state: LessonState,
        lesson: Lesson,
        grader: Grader,
        session_id: int,
    ) -> None:
        # Persistent system prompt is unused — content goes through
        # session.say() and we suppress auto-reply via StopResponse.
        super().__init__(
            instructions=(
                "You are a voice tutor. Speak only when explicitly told to."
            )
        )
        self._state = state
        self._lesson = lesson
        self._grader = grader
        self._session_id = session_id

    async def _save_state(self) -> None:
        """Persist the current LessonState to the backend so a future
        resume can pick up here. Called after every transition."""
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5.0) as http:
                await http.post(
                    f"/sessions/{self._session_id}/state",
                    json={"state_json": self._state.to_dict()},
                )
        except Exception as e:
            logger.warning("Failed to save state: %s", e)

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        # Every early return below is `raise StopResponse()` — once the
        # lesson is over (or the input is unusable), we never want the
        # framework to fall through to its LLM-driven auto-reply.
        if self._state.is_done:
            raise StopResponse()

        user_text = (new_message.text_content or "").strip()
        if not user_text:
            raise StopResponse()
        logger.info("User said: %r", user_text)

        concept = self._state.current_concept
        if concept is None:
            raise StopResponse()

        # Cheat-code path: skip the grader, force-pass.
        if _is_cheat_phrase(user_text):
            logger.info(
                "[CHEAT] phrase=%r — synthetic pass for concept=%s phase_before=%s",
                CHEAT_PHRASE, concept.id, self._state.phase,
            )
            self._state.transition(Grade(score=10, gaps=[]))
            logger.info(
                "Phase after transition: %s (idx=%d)",
                self._state.phase, self._state.idx,
            )
        else:
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
                raise StopResponse()

        # Persist state after every transition (resumption).
        await self._save_state()

        # Dispatch to the next spoken text based on the new phase.
        if self._state.phase == "teach":
            assert self._state.current_concept is not None
            text = prompts.teach_text(self._state.current_concept)
            # Acknowledge the user before the next concept's teach. idx > 0
            # means we just advanced from a prior concept (vs. the boot
            # turn, dispatched from entrypoint with idx=0).
            if self._state.idx > 0:
                text = "Great job! " + text
        elif self._state.phase == "reteach":
            assert self._state.current_concept is not None
            # Reteach text already has its own lead-in.
            text = prompts.reteach_text(
                self._state.current_concept, self._state.last_gaps,
            )
        elif self._state.phase == "done":
            # User just passed the last concept. Closing line already
            # starts with "Great work — you've completed the lesson."
            text = prompts.closing_text(self._lesson.closing)
        else:
            raise StopResponse()

        await self.session.say(text)
        # Suppress the framework's auto-reply — see module docstring.
        raise StopResponse()


async def _fetch_session_info(session_id: int) -> dict:
    """GET /sessions/{id} → {session_id, lesson_id, state_json}.

    Returns {} on failure so the agent can fall back to a default state.
    """
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5.0) as http:
            res = await http.get(f"/sessions/{session_id}")
            res.raise_for_status()
            return res.json()
    except Exception as e:
        logger.warning("Couldn't fetch session info from API: %s", e)
        return {}


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Agent dispatched to room: %s", ctx.room.name)
    await ctx.connect()

    session_id = _parse_session_id_from_room(ctx.room.name)
    if session_id is None:
        logger.error(
            "Could not parse session_id from room name %r — aborting",
            ctx.room.name,
        )
        return

    info = await _fetch_session_info(session_id)
    lesson_id = info.get("lesson_id")
    state_data = info.get("state_json") or {}

    if not lesson_id or lesson_id not in LESSONS:
        logger.error(
            "Unknown or missing lesson_id %r for session %d — aborting",
            lesson_id, session_id,
        )
        return

    lesson = LESSONS[lesson_id]
    state = LessonState.from_dict(lesson.concepts, state_data)
    logger.info(
        "Hydrated session %d: lesson=%s phase=%s idx=%d",
        session_id, lesson_id, state.phase, state.idx,
    )

    grader = Grader()
    agent = TutorAgent(state, lesson, grader, session_id)

    # Pipelined STT + LLM + TTS. The LLM is required by the framework
    # but never invoked via generate_reply — all agent speech goes
    # through session.say().
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=lk_openai.STT(model="whisper-1"),
        llm=lk_openai.LLM(model="gpt-4o-mini"),
        tts=lk_openai.TTS(voice="coral"),
    )

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

    # End the lesson when the closing line finishes speaking.
    @session.on("agent_state_changed")
    def _on_agent_state(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal shutdown_started
        if not state.is_done or shutdown_started:
            return
        old_state = getattr(event, "old_state", None)
        new_state = getattr(event, "new_state", None)
        if old_state == "speaking" and new_state != "speaking":
            shutdown_started = True
            logger.info(
                "Lesson complete (agent finished speaking, %s→%s) — shutting down",
                old_state, new_state,
            )
            ctx.shutdown(reason="lesson_complete")

    await session.start(agent=agent, room=ctx.room)

    # Boot turn — read the current phase's spoken text. On a fresh start
    # this is the first concept's teach. On a resume this is whatever
    # phase the user was in (teach/reteach/done).
    if state.phase == "teach":
        assert state.current_concept is not None
        await session.say(prompts.teach_text(state.current_concept))
    elif state.phase == "reteach":
        assert state.current_concept is not None
        await session.say(prompts.reteach_text(state.current_concept, state.last_gaps))
    elif state.phase == "done":
        # User resumed an already-completed session — speak the closing
        # and let the agent_state_changed handler shut down.
        await session.say(prompts.closing_text(lesson.closing))


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
