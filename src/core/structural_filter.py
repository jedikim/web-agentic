"""Stage 1 structural filter — zero-cost DOM region classification.

Classifies extracted elements into semantic regions (header, nav, main, etc.)
using landmark tags, parent context, ARIA roles, and bounding-box heuristics.
Then filters candidates by intent-region affinity + keyword matching.

Typical reduction: 500+ elements → 20-80 in <5ms with zero LLM cost.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from src.core.types import ExtractedElement


class SemanticRegion(StrEnum):
    """Semantic page regions for structural classification."""

    HEADER = "header"
    NAV = "nav"
    MAIN = "main"
    SIDEBAR = "sidebar"
    FOOTER = "footer"
    DIALOG = "dialog"
    UNKNOWN = "unknown"


# Intent patterns → preferred regions (checked in order).
_INTENT_REGION_MAP: list[tuple[re.Pattern[str], list[SemanticRegion]]] = [
    (
        re.compile(r"(login|sign.?in|로그인|인증|logout|sign.?out|로그아웃)", re.IGNORECASE),
        [SemanticRegion.HEADER, SemanticRegion.DIALOG, SemanticRegion.MAIN],
    ),
    (
        re.compile(r"(search|검색|찾기|query|검색어)", re.IGNORECASE),
        [SemanticRegion.HEADER, SemanticRegion.NAV, SemanticRegion.MAIN],
    ),
    (
        re.compile(r"(menu|category|카테고리|메뉴|nav)", re.IGNORECASE),
        [SemanticRegion.NAV, SemanticRegion.HEADER],
    ),
    (
        re.compile(r"(cart|장바구니|basket|bag)", re.IGNORECASE),
        [SemanticRegion.HEADER],
    ),
    (
        re.compile(r"(footer|copyright|약관|privacy|이용약관|terms)", re.IGNORECASE),
        [SemanticRegion.FOOTER],
    ),
    (
        re.compile(
            r"(product|item|상품|제품|price|가격|결과|result|list|목록|cheapest|buy|구매)",
            re.IGNORECASE,
        ),
        [SemanticRegion.MAIN],
    ),
    (
        re.compile(r"(sidebar|side.?bar|filter|필터|refine)", re.IGNORECASE),
        [SemanticRegion.SIDEBAR],
    ),
    (
        re.compile(r"(popup|modal|dialog|팝업|닫기|close|dismiss|confirm|확인)", re.IGNORECASE),
        [SemanticRegion.DIALOG],
    ),
]

# Landmark tag → SemanticRegion mapping.
_LANDMARK_MAP: dict[str, SemanticRegion] = {
    "nav": SemanticRegion.NAV,
    "header": SemanticRegion.HEADER,
    "footer": SemanticRegion.FOOTER,
    "aside": SemanticRegion.SIDEBAR,
    "main": SemanticRegion.MAIN,
    "section": SemanticRegion.MAIN,
}

# Parent-context keywords → SemanticRegion.
_PARENT_KEYWORDS: list[tuple[str, SemanticRegion]] = [
    ("nav", SemanticRegion.NAV),
    ("header", SemanticRegion.HEADER),
    ("footer", SemanticRegion.FOOTER),
    ("sidebar", SemanticRegion.SIDEBAR),
    ("aside", SemanticRegion.SIDEBAR),
    ("dialog", SemanticRegion.DIALOG),
    ("modal", SemanticRegion.DIALOG),
    ("main", SemanticRegion.MAIN),
]

# ARIA role → SemanticRegion.
_ROLE_MAP: dict[str, SemanticRegion] = {
    "navigation": SemanticRegion.NAV,
    "banner": SemanticRegion.HEADER,
    "contentinfo": SemanticRegion.FOOTER,
    "complementary": SemanticRegion.SIDEBAR,
    "main": SemanticRegion.MAIN,
    "dialog": SemanticRegion.DIALOG,
    "alertdialog": SemanticRegion.DIALOG,
}

# Default viewport height for bbox-based classification.
_DEFAULT_VIEWPORT_HEIGHT = 1080


def classify_region(
    el: ExtractedElement,
    viewport_height: int = _DEFAULT_VIEWPORT_HEIGHT,
) -> SemanticRegion:
    """Classify an element into a semantic page region.

    Priority:
        1. landmark field (from closest landmark tag)
        2. parent_context keywords
        3. ARIA role
        4. Bounding-box heuristic (y position)
        5. UNKNOWN fallback

    Args:
        el: Extracted DOM element.
        viewport_height: Current viewport height for bbox heuristics.

    Returns:
        SemanticRegion classification.
    """
    # 1. Landmark tag
    if el.landmark:
        region = _LANDMARK_MAP.get(el.landmark)
        if region is not None:
            return region

    # 2. Parent context keywords
    if el.parent_context:
        ctx_lower = el.parent_context.lower()
        for keyword, region in _PARENT_KEYWORDS:
            if keyword in ctx_lower:
                return region

    # 3. ARIA role
    if el.role:
        region = _ROLE_MAP.get(el.role)
        if region is not None:
            return region

    # 4. Bounding-box heuristic
    y = el.bbox[1]
    if y < 150:
        return SemanticRegion.HEADER
    if y > viewport_height - 150:
        return SemanticRegion.FOOTER

    return SemanticRegion.UNKNOWN


def _preferred_regions(intent: str) -> list[SemanticRegion]:
    """Extract preferred semantic regions from an intent string."""
    regions: list[SemanticRegion] = []
    for pattern, region_list in _INTENT_REGION_MAP:
        if pattern.search(intent):
            for r in region_list:
                if r not in regions:
                    regions.append(r)
    return regions


def _keyword_score(el: ExtractedElement, words: list[str]) -> int:
    """Score an element by keyword overlap with intent words."""
    txt = (el.text or "").lower()
    ctx = (el.parent_context or "").lower()
    combined = txt + " " + ctx
    return sum(1 for w in words if w in combined)


class StructuralFilter:
    """Stage 1 structural filter — region classification + keyword ranking.

    Reduces candidates to max_candidates using:
    1. Semantic region affinity to intent
    2. Keyword matching within preferred regions
    3. Backfill from remaining regions

    Args:
        max_candidates: Maximum number of candidates to return.
        viewport_height: Viewport height for bbox-based classification.
    """

    def __init__(
        self,
        max_candidates: int = 80,
        viewport_height: int = _DEFAULT_VIEWPORT_HEIGHT,
    ) -> None:
        self._max_candidates = max_candidates
        self._viewport_height = viewport_height

    def filter(
        self,
        candidates: Sequence[ExtractedElement],
        intent: str,
    ) -> list[ExtractedElement]:
        """Filter and rank candidates by structural affinity to intent.

        Args:
            candidates: All extracted DOM elements.
            intent: User intent string.

        Returns:
            Filtered list of up to max_candidates elements, preferred-region first.
        """
        if len(candidates) <= self._max_candidates:
            return list(candidates)

        # Classify all elements
        classified: dict[SemanticRegion, list[ExtractedElement]] = {}
        for el in candidates:
            region = classify_region(el, self._viewport_height)
            classified.setdefault(region, []).append(el)

        # Get preferred regions for this intent
        preferred = _preferred_regions(intent)

        # Extract keywords for scoring
        words = re.findall(r"[\w가-힣]{2,}", intent.lower())

        result: list[ExtractedElement] = []
        used: set[str] = set()

        # Phase 1: Preferred-region elements, sorted by keyword score
        for region in preferred:
            region_els = classified.get(region, [])
            region_els.sort(key=lambda el: _keyword_score(el, words), reverse=True)
            for el in region_els:
                if el.eid not in used:
                    result.append(el)
                    used.add(el.eid)

        # Phase 2: UNKNOWN + remaining regions, sorted by keyword score
        remaining: list[ExtractedElement] = []
        for region, els in classified.items():
            if region not in preferred:
                remaining.extend(el for el in els if el.eid not in used)
        remaining.sort(key=lambda el: _keyword_score(el, words), reverse=True)
        result.extend(remaining)

        return result[: self._max_candidates]
