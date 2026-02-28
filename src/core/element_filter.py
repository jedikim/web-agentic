"""Element Filter — TextMatcher-based DOM node filtering.

Replaces the old 2-stage StructuralFilter + VectorRanker pipeline with
a simpler keyword_weights scoring approach (Prune4Web).

The Planner generates keyword_weights for each step, and the filter
scores DOM nodes against those weights to find the best candidates.

Usage:
    filter = ElementFilter()
    scored = filter.filter(nodes, {"검색": 1.0, "query": 0.8})
"""

from __future__ import annotations

from src.core.text_matcher import TextMatcher
from src.core.types import DOMNode, ScoredNode

# Minimum score threshold to include a node in results
FILTER_SCORE_THRESHOLD = 0.5


class ElementFilter:
    """Filter DOM nodes using TextMatcher keyword_weights scoring.

    Attributes:
        _matcher: TextMatcher instance for scoring nodes.
    """

    def __init__(self, matcher: TextMatcher | None = None) -> None:
        self._matcher = matcher or TextMatcher()

    def filter(
        self,
        nodes: list[DOMNode],
        keyword_weights: dict[str, float],
        top_k: int = 20,
    ) -> list[ScoredNode]:
        """Score and filter nodes by keyword_weights.

        Args:
            nodes: DOM nodes from DOMExtractor.
            keyword_weights: Planner-generated keyword -> weight mapping.
            top_k: Maximum results to return.

        Returns:
            Top-K scored nodes sorted by score descending.
        """
        return self._matcher.filter_nodes(nodes, keyword_weights, top_k)

    def filter_with_threshold(
        self,
        nodes: list[DOMNode],
        keyword_weights: dict[str, float],
        threshold: float = FILTER_SCORE_THRESHOLD,
        top_k: int = 20,
    ) -> list[ScoredNode]:
        """Score and filter nodes, only returning nodes above threshold.

        Args:
            nodes: DOM nodes from DOMExtractor.
            keyword_weights: Planner-generated keyword -> weight mapping.
            threshold: Minimum score to include.
            top_k: Maximum results to return.

        Returns:
            Scored nodes above threshold, sorted by score descending.
        """
        scored = self._matcher.filter_nodes(nodes, keyword_weights, top_k=len(nodes))
        filtered = [s for s in scored if s.score >= threshold]
        return filtered[:top_k]

    @property
    def matcher(self) -> TextMatcher:
        """Access the underlying TextMatcher."""
        return self._matcher
