"""Context Reducer — builds compact candidate context for LLM prompts.

Sorts DOM candidates by score, trims to *max_candidates*, and strips
heavyweight attributes so that the LLM receives a minimal, high-signal
context window.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Data Models ──────────────────────────────────────


@dataclass(frozen=True)
class CandidateItem:
    """A single DOM candidate with optional extra attributes."""

    id: str
    role: str
    text: str
    score: float
    bbox: tuple[int, int, int, int]
    attributes: dict[str, str] | None = None


@dataclass(frozen=True)
class ReducedCandidate:
    """A candidate stripped of heavyweight attributes."""

    id: str
    role: str
    text: str
    score: float
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class CandidateContext:
    """The reduced set of candidates ready for LLM consumption."""

    candidates: list[ReducedCandidate] = field(default_factory=list)


# ── Public API ───────────────────────────────────────


def build_candidate_context(
    items: list[CandidateItem],
    max_candidates: int = 8,
) -> CandidateContext:
    """Build a compact candidate context from raw candidates.

    Args:
        items: Raw candidate items extracted from the DOM.
        max_candidates: Maximum number of candidates to keep (at least 1).

    Returns:
        A ``CandidateContext`` containing the top-N candidates sorted by
        score descending, with attributes stripped.
    """
    limit = max(1, max_candidates)
    sorted_items = sorted(items, key=lambda c: c.score, reverse=True)
    top = sorted_items[:limit]

    candidates = [
        ReducedCandidate(
            id=item.id,
            role=item.role,
            text=item.text,
            score=item.score,
            bbox=item.bbox,
        )
        for item in top
    ]
    return CandidateContext(candidates=candidates)
