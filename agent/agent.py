"""LiveKit voice tutor agent worker — state-machine driven, static content.

Per-session orchestration:
  1. On dispatch, fetch session metadata from /sessions/by-room/{room}.
  2. Build a LessonState over the lesson's concept list.
  3. TutorAgent.session.say() the first concept's teach text.
  4. After each user turn, on_user_turn_completed hook fires BEFORE the
     agent responds:
       a. Call externalized grader (gpt-4o-mini, JSON schema) → {score, gaps}.
       b. state.transition(grade) — Python branch decides next phase.
       c. session.say(text) for the next phase's curated content.
  5. On shutdown, POST collected transcript to /sessions/end.

The only LLM call in the per-turn loop is the grader. The agent's own
voice output goes through `session.say()` which bypasses the LLM entirely
— teach/reteach/synthesis content is read verbatim from `lesson.py` /
`prompts.py`. AgentSession's LLM is required by the framework but never
invoked for content generation.

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
from lesson import LESSON
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


class TutorAgent(Agent):
    """Agent that runs the structured loop. Hook fires before each agent reply."""

    def __init__(self, state: LessonState, grader: Grader) -> None:
        # Minimal persistent system prompt — content comes from session.say()
        # in our hook, not from the LLM, so this prompt is essentially unused.
        super().__init__(
            instructions=(
                "You are a voice tutor for HTTP, WebSockets, and WebRTC. "
                "Speak only when explicitly told to."
            )
        )
        self._state = state
        self._grader = grader

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

        # Cheat-code path: skip the grader, force-pass. Lets the developer
        # walk through a full lesson quickly during testing/demos without
        # giving real answers. Logged distinctly so it's obvious in tails.
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

        # Dispatch to the next spoken text based on the new phase.
        if self._state.phase == "teach":
            assert self._state.current_concept is not None
            text = prompts.teach_text(self._state.current_concept)
            # Acknowledge the user before the next concept's teach. idx > 0
            # means we just advanced from a prior concept (vs. the boot
            # turn, which is dispatched from entrypoint with idx=0 and
            # doesn't hit this code path).
            if self._state.idx > 0:
                text = "Great job! " + text
        elif self._state.phase == "reteach":
            assert self._state.current_concept is not None
            # Reteach text already has its own lead-in ("Let me walk
            # through that one more time"), so no extra acknowledgment.
            text = prompts.reteach_text(
                self._state.current_concept, self._state.last_gaps,
            )
        elif self._state.phase == "done":
            # User just passed the last concept. The closing line already
            # starts with "Great work — you've completed the lesson," so
            # no extra acknowledgment.
            text = prompts.closing_text()
        else:
            raise StopResponse()

        await self.session.say(text)
        # Suppress the framework's auto-reply. Without this, after our
        # session.say() returns the framework calls generate_reply() and
        # the LLM produces an additional unscripted utterance — the
        # rambling we observed after the closing line. All agent speech
        # in this app is curated and routed through session.say(); the
        # auto-reply is an unintended second mouth.
        raise StopResponse()


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

    state = LessonState(lesson=LESSON)
    grader = Grader()
    agent = TutorAgent(state, grader)

    # Pipelined STT + LLM + TTS (all OpenAI, plus Silero for VAD). The LLM
    # here is required by the framework but is never invoked via
    # generate_reply — all of the agent's spoken content goes through
    # session.say() which bypasses the LLM and feeds TTS directly.
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=lk_openai.STT(model="whisper-1"),
        llm=lk_openai.LLM(model="gpt-4o-mini"),
        tts=lk_openai.TTS(voice="coral"),
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

    # End the lesson when the closing line finishes speaking.
    # state.is_done flips to True the moment the user passes the last
    # concept; the hook then triggers the closing line via session.say().
    # The agent transitions listening→thinking→speaking→listening to
    # utter the closing; we must wait for the final speaking→non-speaking
    # edge before shutting down, otherwise we'd cut off the audio.
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

    async def _on_shutdown() -> None:
        await _post_session_end(ctx.room.name, collected)

    ctx.add_shutdown_callback(_on_shutdown)

    await session.start(agent=agent, room=ctx.room)
    # Kick off the first TEACH turn — read the curated content directly via TTS.
    assert state.current_concept is not None
    await session.say(prompts.teach_text(state.current_concept))


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
