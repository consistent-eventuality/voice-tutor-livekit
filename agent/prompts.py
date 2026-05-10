"""Spoken-text builders for the structured tutoring loop.

Each function returns the exact text the agent will say via
`AgentSession.say()` — no LLM is involved in producing this content. The
realtime model's `generate_reply` path is bypassed entirely; the only
LLM call in the agent flow is the grader.

Three phases get spoken text:
  * teach      — read the concept's curated content, ask a recall question
  * reteach    — re-read the concept with a brief lead-in (v1)
  * synthesis  — read the lesson-level closing summary
"""

from __future__ import annotations

from lesson import Concept


def teach_text(concept: Concept) -> str:
    return f"{concept.teach} What's your understanding of {concept.name}?"


def reteach_text(concept: Concept, gaps: list[str]) -> str:
    """Spoken text for the reteach phase.

    v1: re-reads the concept's curated teach content with a brief lead-in.
    The `gaps` argument is accepted but unused — the grader's specific
    feedback on what the user missed is preserved in `state.last_gaps`
    for the future enhancement.

    Future enhancement: replace the static re-read with a separate
    `gpt-4o-mini` text-completion call (e.g. an `agent/reteacher.py`
    module mirroring `agent/grader.py`) that takes (concept, gaps) and
    produces a 2-3 sentence explanation tailored to the user's specific
    misunderstanding. The state machine and gap plumbing already support
    this — only this function needs to change.
    """
    _ = gaps  # parked for the future tailored-reteach enhancement
    return (
        f"Let me walk through that one more time. "
        f"{concept.teach} What's your understanding of {concept.name} now?"
    )


def closing_text(closing: str) -> str:
    """Brief spoken line after the user has passed every concept.

    Audibly signals the end of the lesson before the session disconnects.
    Takes the closing string from the active Lesson rather than a global
    constant so each lesson can have its own sign-off.
    """
    return closing
