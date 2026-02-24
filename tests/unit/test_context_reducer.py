"""Unit tests for Context Reducer — ``src.ai.context_reducer``."""
from __future__ import annotations

from src.ai.context_reducer import (
    CandidateContext,
    CandidateItem,
    ReducedCandidate,
    build_candidate_context,
)

# ── Helpers ──────────────────────────────────────────


def _item(
    item_id: str = "e1",
    role: str = "button",
    text: str = "Click",
    score: float = 0.9,
    bbox: tuple[int, int, int, int] = (0, 0, 100, 50),
    attributes: dict[str, str] | None = None,
) -> CandidateItem:
    return CandidateItem(
        id=item_id, role=role, text=text, score=score, bbox=bbox, attributes=attributes
    )


# ── Tests ────────────────────────────────────────────


class TestBuildCandidateContext:
    """Tests for build_candidate_context."""

    def test_empty_items_returns_empty(self) -> None:
        """Empty input produces an empty CandidateContext."""
        ctx = build_candidate_context([])
        assert ctx == CandidateContext(candidates=[])
        assert len(ctx.candidates) == 0

    def test_single_item_preserved(self) -> None:
        """A single candidate is preserved in the output."""
        item = _item(item_id="e1", score=0.5)
        ctx = build_candidate_context([item])
        assert len(ctx.candidates) == 1
        assert ctx.candidates[0].id == "e1"
        assert ctx.candidates[0].score == 0.5

    def test_items_sorted_by_score_desc(self) -> None:
        """Candidates are returned in descending score order."""
        items = [
            _item(item_id="low", score=0.1),
            _item(item_id="high", score=0.9),
            _item(item_id="mid", score=0.5),
        ]
        ctx = build_candidate_context(items)
        ids = [c.id for c in ctx.candidates]
        assert ids == ["high", "mid", "low"]

    def test_max_candidates_limit(self) -> None:
        """Output is truncated to max_candidates."""
        items = [_item(item_id=f"e{i}", score=float(i)) for i in range(10)]
        ctx = build_candidate_context(items, max_candidates=3)
        assert len(ctx.candidates) == 3
        # Top 3 by score: e9, e8, e7
        ids = [c.id for c in ctx.candidates]
        assert ids == ["e9", "e8", "e7"]

    def test_attributes_stripped(self) -> None:
        """Attributes from CandidateItem are not present in ReducedCandidate."""
        item = _item(attributes={"data-testid": "btn", "class": "primary"})
        ctx = build_candidate_context([item])
        candidate = ctx.candidates[0]
        assert isinstance(candidate, ReducedCandidate)
        assert not hasattr(candidate, "attributes")

    def test_min_one_candidate(self) -> None:
        """Even with max_candidates=0 or negative, at least 1 is returned."""
        items = [_item(item_id="only")]
        ctx_zero = build_candidate_context(items, max_candidates=0)
        assert len(ctx_zero.candidates) == 1
        ctx_neg = build_candidate_context(items, max_candidates=-5)
        assert len(ctx_neg.candidates) == 1

    def test_default_max_is_8(self) -> None:
        """Default max_candidates is 8."""
        items = [_item(item_id=f"e{i}", score=float(i)) for i in range(15)]
        ctx = build_candidate_context(items)
        assert len(ctx.candidates) == 8

    def test_bbox_preserved(self) -> None:
        """Bounding box tuple is faithfully carried to ReducedCandidate."""
        bbox = (10, 20, 300, 400)
        item = _item(bbox=bbox)
        ctx = build_candidate_context([item])
        assert ctx.candidates[0].bbox == bbox
