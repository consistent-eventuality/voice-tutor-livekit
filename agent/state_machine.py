"""Pure-Python state machine for a single lesson.

Owns the deterministic if-statements that decide what comes next. No I/O,
no LLM calls, easy to unit test. The realtime agent and grader sit on
either side of this.

States:
    teach        — about to teach the current concept (initial state per concept)
    reteach      — current concept's first attempt failed; one re-attempt allowed
    synthesize   — all concepts covered, about to wrap up
    done         — synthesis sent, lesson over
"""

from __future__ import annotations

from dataclasses import dataclass

import prompts
from curriculum import Concept

PASS_THRESHOLD = 7  # ≥ this is "good enough to move on"


@dataclass
class Grade:
    score: int  # 1-10
    gaps: list[str]


class LessonState:
    def __init__(self, curriculum: list[Concept]) -> None:
        self.curriculum = curriculum
        self.idx = 0
        self.phase: str = "teach"  # teach | reteach | synthesize | done
        self.last_gaps: list[str] = []

    @property
    def current_concept(self) -> Concept | None:
        if self.idx >= len(self.curriculum):
            return None
        return self.curriculum[self.idx]

    @property
    def is_done(self) -> bool:
        return self.phase == "done"

    def transition(self, grade: Grade) -> None:
        """Apply a grade to the current concept and advance.

        teach     + pass → next concept (or synthesize if last)
        teach     + fail → reteach (gaps recorded)
        reteach   + any  → next concept regardless (one re-attempt only)
        """
        if self.phase == "teach":
            if grade.score >= PASS_THRESHOLD:
                self._advance()
            else:
                self.phase = "reteach"
                self.last_gaps = grade.gaps
        elif self.phase == "reteach":
            self._advance()
        # synthesize / done — no further transitions on grades

    def _advance(self) -> None:
        self.idx += 1
        if self.idx >= len(self.curriculum):
            self.phase = "synthesize"
        else:
            self.phase = "teach"
            self.last_gaps = []

    def mark_synthesized(self) -> None:
        self.phase = "done"

    def current_instruction(self) -> str:
        """Return the prompt for the agent's NEXT turn, given the current phase."""
        if self.phase == "teach":
            assert self.current_concept is not None
            return prompts.teach(self.current_concept)
        if self.phase == "reteach":
            assert self.current_concept is not None
            return prompts.reteach(self.current_concept, self.last_gaps)
        if self.phase == "synthesize":
            return prompts.synthesize(self.curriculum)
        return ""  # done
