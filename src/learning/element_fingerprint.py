"""Similo multi-attribute element fingerprinting for selector recovery.

Based on the Similo approach (ACM TOSEM 2023): when a selector breaks,
match elements by multi-attribute similarity instead of calling LLM.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)


# ── Data Types ──────────────────────────────────────


@dataclass(frozen=True)
class ElementFingerprint:
    """Multi-attribute fingerprint of a DOM element.

    Attributes:
        tag: HTML tag name (e.g. "button", "input").
        role: ARIA role (e.g. "button", "textbox").
        text: Visible text content.
        class_list: Tuple of CSS class names.
        nearby_text: Text from surrounding/sibling elements.
        bbox: Bounding box as (x, y, width, height).
        attributes_hash: SHA-256 hash of sorted key=value attribute pairs.
    """

    tag: str
    role: str = ""
    text: str = ""
    class_list: tuple[str, ...] = ()
    nearby_text: str = ""
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    attributes_hash: str = ""


@dataclass(frozen=True)
class FingerprintMatch:
    """Result of a fingerprint similarity search.

    Attributes:
        score: Overall similarity score in [0.0, 1.0].
        matched_eid: Element ID of the best matching candidate.
        breakdown: Per-attribute similarity scores.
    """

    score: float
    matched_eid: str
    breakdown: dict[str, float]


# ── Default Weights ─────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "tag": 0.20,
    "role": 0.15,
    "text": 0.25,
    "class_list": 0.15,
    "nearby_text": 0.10,
    "bbox": 0.05,
    "attributes_hash": 0.10,
}


# ── Internal Helpers ────────────────────────────────


def _exact_match(a: str, b: str) -> float:
    """Return 1.0 if strings are equal (case-insensitive), else 0.0."""
    return 1.0 if a.lower() == b.lower() else 0.0


def _text_similarity(a: str, b: str) -> float:
    """Fuzzy text similarity using SequenceMatcher.

    Returns 1.0 if both strings are empty, 0.0 if only one is empty.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _class_list_similarity(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Jaccard similarity between two class lists."""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _bbox_similarity(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> float:
    """Bounding-box similarity based on normalized Manhattan distance.

    Returns 1.0 for identical boxes, decreasing toward 0.0 as they diverge.
    """
    if a == b:
        return 1.0
    if a == (0, 0, 0, 0) or b == (0, 0, 0, 0):
        return 0.0
    # Normalized distance per component
    max_dim = max(
        max(abs(a[0]), abs(b[0]), 1),
        max(abs(a[1]), abs(b[1]), 1),
        max(abs(a[2]), abs(b[2]), 1),
        max(abs(a[3]), abs(b[3]), 1),
    )
    dist = sum(abs(ai - bi) for ai, bi in zip(a, b, strict=True)) / (4 * max_dim)
    return max(0.0, 1.0 - dist)


# ── Public API ──────────────────────────────────────


def compute_fingerprint(
    tag: str,
    role: str = "",
    text: str = "",
    class_list: tuple[str, ...] | list[str] = (),
    nearby_text: str = "",
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0),
    attributes: dict[str, str] | None = None,
) -> ElementFingerprint:
    """Build an ElementFingerprint from raw element data.

    Args:
        tag: HTML tag name.
        role: ARIA role string.
        text: Visible text content.
        class_list: CSS class names (list or tuple).
        nearby_text: Text from nearby/sibling elements.
        bbox: Bounding box (x, y, width, height).
        attributes: Raw HTML attributes dict for hashing.

    Returns:
        A frozen ElementFingerprint.
    """
    cls = tuple(class_list) if isinstance(class_list, list) else class_list
    attr_hash = ""
    if attributes:
        sorted_pairs = sorted(attributes.items())
        raw = "&".join(f"{k}={v}" for k, v in sorted_pairs)
        attr_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return ElementFingerprint(
        tag=tag,
        role=role,
        text=text,
        class_list=cls,
        nearby_text=nearby_text,
        bbox=bbox,
        attributes_hash=attr_hash,
    )


def score_similarity(
    fp1: ElementFingerprint,
    fp2: ElementFingerprint,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute weighted similarity between two fingerprints.

    Args:
        fp1: Reference fingerprint.
        fp2: Candidate fingerprint.
        weights: Per-attribute weight dict. Uses DEFAULT_WEIGHTS if None.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    w = weights or DEFAULT_WEIGHTS
    scores: dict[str, float] = {
        "tag": _exact_match(fp1.tag, fp2.tag),
        "role": _exact_match(fp1.role, fp2.role),
        "text": _text_similarity(fp1.text, fp2.text),
        "class_list": _class_list_similarity(fp1.class_list, fp2.class_list),
        "nearby_text": _text_similarity(fp1.nearby_text, fp2.nearby_text),
        "bbox": _bbox_similarity(fp1.bbox, fp2.bbox),
        "attributes_hash": _exact_match(fp1.attributes_hash, fp2.attributes_hash),
    }
    total_weight = sum(w.get(k, 0.0) for k in scores)
    if total_weight == 0:
        return 0.0
    return sum(w.get(k, 0.0) * v for k, v in scores.items()) / total_weight


def find_best_match(
    reference: ElementFingerprint,
    candidates: list[tuple[str, ElementFingerprint]],
    threshold: float = 0.6,
    weights: dict[str, float] | None = None,
) -> FingerprintMatch | None:
    """Find the best matching candidate above threshold.

    Args:
        reference: The fingerprint to match against.
        candidates: List of (element_id, fingerprint) tuples.
        threshold: Minimum similarity to consider a match.
        weights: Optional custom weights.

    Returns:
        FingerprintMatch if a candidate exceeds threshold, else None.
    """
    if not candidates:
        return None

    best_score = 0.0
    best_eid = ""
    best_breakdown: dict[str, float] = {}

    w = weights or DEFAULT_WEIGHTS
    for eid, fp in candidates:
        scores: dict[str, float] = {
            "tag": _exact_match(reference.tag, fp.tag),
            "role": _exact_match(reference.role, fp.role),
            "text": _text_similarity(reference.text, fp.text),
            "class_list": _class_list_similarity(reference.class_list, fp.class_list),
            "nearby_text": _text_similarity(reference.nearby_text, fp.nearby_text),
            "bbox": _bbox_similarity(reference.bbox, fp.bbox),
            "attributes_hash": _exact_match(
                reference.attributes_hash, fp.attributes_hash
            ),
        }
        total_weight = sum(w.get(k, 0.0) for k in scores)
        if total_weight == 0:
            continue
        overall = sum(w.get(k, 0.0) * v for k, v in scores.items()) / total_weight
        if overall > best_score:
            best_score = overall
            best_eid = eid
            best_breakdown = scores

    if best_score < threshold:
        return None

    return FingerprintMatch(
        score=best_score,
        matched_eid=best_eid,
        breakdown=best_breakdown,
    )


def serialize_fingerprint(fp: ElementFingerprint) -> dict[str, Any]:
    """Serialize a fingerprint to a JSON-compatible dict.

    Args:
        fp: The fingerprint to serialize.

    Returns:
        Dict representation.
    """
    return {
        "tag": fp.tag,
        "role": fp.role,
        "text": fp.text,
        "class_list": list(fp.class_list),
        "nearby_text": fp.nearby_text,
        "bbox": list(fp.bbox),
        "attributes_hash": fp.attributes_hash,
    }


def deserialize_fingerprint(data: dict[str, Any]) -> ElementFingerprint:
    """Deserialize a fingerprint from a dict.

    Args:
        data: Dict with fingerprint fields.

    Returns:
        Reconstructed ElementFingerprint.
    """
    return ElementFingerprint(
        tag=data["tag"],
        role=data.get("role", ""),
        text=data.get("text", ""),
        class_list=tuple(data.get("class_list", ())),
        nearby_text=data.get("nearby_text", ""),
        bbox=tuple(data.get("bbox", (0, 0, 0, 0))),
        attributes_hash=data.get("attributes_hash", ""),
    )
