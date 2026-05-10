"""Externalized grader — separate gpt-4o-mini call with enforced JSON schema.

Run after each user response. Returns a Grade(score, gaps) that the state
machine consumes. The realtime agent never grades itself; this is the
deterministic, API-validated source of truth.

response_format with strict JSON schema means the API will not return
malformed output. We can rely on Grade(...) constructing cleanly.
"""

from __future__ import annotations

import json
import logging
import os

from openai import AsyncOpenAI

from curriculum import Concept
from state_machine import Grade

logger = logging.getLogger("voice-tutor-agent.grader")


GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "1 = no understanding, 10 = fully grasped",
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific aspects of the concept the user missed or got wrong",
        },
    },
    "required": ["score", "gaps"],
    "additionalProperties": False,
}


class Grader:
    def __init__(self, model: str | None = None) -> None:
        self._client = AsyncOpenAI()
        self._model = model or os.environ.get("GRADER_MODEL", "gpt-4o-mini")

    async def grade(self, concept: Concept, user_text: str) -> Grade:
        rubric_lines = "\n".join(
            f"- {r.description} (e.g.: {r.ideal_answer})"
            for r in concept.rubric
        )
        system = (
            f"You are a strict grader of conceptual understanding. Score the "
            f"user's grasp of {concept.name} from 1 (no understanding) to 10 "
            f"(fully grasped).\n\n"
            f"Rubric — what to check for:\n{rubric_lines}\n\n"
            f"Be honest, not polite. Hand-wavy or partial answers should "
            f"score below 7. Don't reward confidence — reward accuracy and "
            f"specificity. List concrete gaps in the 'gaps' field."
        )

        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"The user said:\n\n{user_text}"},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "grade",
                        "schema": GRADE_SCHEMA,
                        "strict": True,
                    },
                },
                temperature=0.2,
            )
            content = resp.choices[0].message.content or "{}"
            parsed = json.loads(content)
            return Grade(score=int(parsed["score"]), gaps=list(parsed.get("gaps", [])))
        except Exception as e:
            logger.warning("Grader failed (%s); defaulting to pass score 7", e)
            # Fail open: if grader errors, treat as a pass so we don't loop on reteach
            return Grade(score=7, gaps=[])
