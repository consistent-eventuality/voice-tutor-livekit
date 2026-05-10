"""Pure-Python state machine for a single lesson.

Owns the deterministic if-statements that decide what comes next. No I/O,
no LLM calls, easy to unit test. The realtime agent and grader sit on
either side of this.

States:
    teach    — about to teach the current concept (initial state per concept)
    reteach  — last attempt on the current concept failed; will re-explain
    done     — user has passed every concept in the lesson

Transition rule (simple):
    pass (score >= PASS_THRESHOLD) → advance to next concept (or done if last)
    fail (score < PASS_THRESHOLD)  → reteach (record gaps), stay on concept

Synthesis is just the last concept in `LESSON`, no longer a special phase.
The lesson ends when the user passes the last concept; the agent then
speaks a brief closing line (handled in agent.py, not here).

A user who keeps failing stays on the same concept indefinitely. Future
enhancements (parked):
    - upper bound on reteach attempts (after N misses, advance regardless)
    - user-facing "skip" option ("I want to move on")
    - tailored reteach via a Reteacher LLM that uses last_gaps
"""

from __future__ import annotations

from dataclasses import dataclass

from lesson import Concept

PASS_THRESHOLD = 2  # ≥ this is "good enough to move on"


@dataclass
class Grade:
    score: int  # 1-10
    gaps: list[str]


class LessonState:
    def __init__(self, lesson: list[Concept]) -> None:
        self.lesson = lesson
        self.idx = 0
        self.phase: str = "teach"  # teach | reteach | done
        self.last_gaps: list[str] = []

    @property
    def current_concept(self) -> Concept | None:
        if self.idx >= len(self.lesson):
            return None
        return self.lesson[self.idx]

    @property
    def is_done(self) -> bool:
        return self.phase == "done"

    def transition(self, grade: Grade) -> None:
        """Apply a grade to the current concept.

        pass → advance to next concept (or synthesize if last)
        fail → reteach (gaps recorded), stay on the same concept

        The teach/reteach distinction is purely about spoken wording —
        a fresh concept opens with `teach` (no lead-in), subsequent
        re-attempts use `reteach` (with a brief lead-in).
        """
        if self.phase in ("teach", "reteach"):
            if grade.score >= PASS_THRESHOLD:
                self._advance()
            else:
                self.phase = "reteach"
                self.last_gaps = grade.gaps
        # synthesize / done — no further transitions on grades

    def _advance(self) -> None:
        self.idx += 1
        if self.idx >= len(self.lesson):
            self.phase = "done"
        else:
            self.phase = "teach"
            self.last_gaps = []

    # --- serialization for per-transition persistence ---

    def to_dict(self) -> dict:
        return {
            "idx": self.idx,
            "phase": self.phase,
            "last_gaps": list(self.last_gaps),
        }

    @classmethod
    def from_dict(cls, lesson: list[Concept], data: dict) -> "LessonState":
        """Reconstruct a state from a previously serialized dict.

        Defensive against missing/extra keys — falls back to a fresh state
        if anything looks wrong, so a corrupt state_json never blocks a
        user from using a lesson.
        """
        state = cls(lesson)
        try:
            state.idx = int(data.get("idx", 0))
            phase = data.get("phase", "teach")
            if phase not in ("teach", "reteach", "done"):
                phase = "teach"
            state.phase = phase
            gaps = data.get("last_gaps", [])
            state.last_gaps = list(gaps) if isinstance(gaps, list) else []
            # Clamp idx within bounds
            if state.idx < 0 or state.idx > len(lesson):
                state.idx = 0
                state.phase = "teach"
                state.last_gaps = []
        except (TypeError, ValueError):
            state = cls(lesson)
        return state
