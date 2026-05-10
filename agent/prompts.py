"""Focused, single-purpose prompts driven by the lesson state machine.

Each function returns the instruction the realtime agent receives for ONE
turn. We push these via session.generate_reply(instructions=...) so the
agent's persistent system prompt stays minimal — every turn sees exactly
one job.

These prompts are first-cut fixture, not iteratively tuned. The artifact
is the orchestration boundary, not the wording.
"""

from __future__ import annotations

from curriculum import Concept


def teach(concept: Concept) -> str:
    return (
        f"You are about to teach one specific concept. Do this once, then "
        f"stop and wait for the user.\n\n"
        f"Step 1: Explain {concept.name} in 2-3 sentences. Use this content "
        f"as your reference, in your own words:\n"
        f"{concept.teach}\n\n"
        f'Step 2: End your turn by asking: "{concept.recall_prompt}"\n\n'
        f"Don't grade their previous answer. Don't continue past the question. "
        f"Just teach + ask + stop."
    )


def reteach(concept: Concept, gaps: list[str]) -> str:
    gap_text = "; ".join(gaps) if gaps else "the core idea"
    return (
        f"The user struggled with {concept.name}, specifically: {gap_text}.\n\n"
        f"Re-explain in different words, addressing that gap directly. Be "
        f"more concrete or use an analogy. Then ask: "
        f'"{concept.recall_prompt}"\n\n'
        f"Don't apologize or signal that you're re-teaching. Just teach "
        f"better. Then stop."
    )


def synthesize(curriculum: list[Concept]) -> str:
    names = ", ".join(c.name for c in curriculum)
    return (
        f"You've covered: {names}. In 2-3 sentences, tie them together — "
        f"how they relate, when each is the right tool. Then end by saying "
        f'something like "great work, hit disconnect when you\'re ready." '
        f"Then stop."
    )
