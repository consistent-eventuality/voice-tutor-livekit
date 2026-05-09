"""LiveKit voice tutor agent worker.

Runs as a separate process. Registers with LiveKit Cloud and gets dispatched
into rooms when users join. One agent process can serve multiple concurrent
sessions; scale horizontally by running more processes (k8s/ECS).

Run locally:
    python agent.py dev      # hot-reload, attaches to LiveKit Cloud
    python agent.py start    # production worker

Required env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai

load_dotenv()

logger = logging.getLogger("voice-tutor-agent")
logging.basicConfig(level=logging.INFO)


TUTOR_INSTRUCTIONS = (
    "You are a friendly, patient voice tutor. "
    "Greet the user warmly and ask what they'd like to learn about today. "
    "Once they pick a topic, teach in short, conversational turns: explain a "
    "concept in 2-3 sentences, then ask a check-in question to make sure they "
    "follow. Keep your tone encouraging. The subject is open-ended for now."
)


class TutorAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=TUTOR_INSTRUCTIONS)


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Agent dispatched to room: %s", ctx.room.name)
    await ctx.connect()

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
    #
    # Tradeoff: pipelined gives finer control over each stage (better TTS quality,
    # easier model swaps) at the cost of 4 API keys, 4 plugins, and ~300ms more
    # end-to-end latency. OpenAI Realtime is the right call for the take-home.

    await session.start(agent=TutorAgent(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
