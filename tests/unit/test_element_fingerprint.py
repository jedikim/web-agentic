"""Unit tests for Similo multi-attribute element fingerprinting.

Covers fingerprint creation, similarity scoring, best-match search,
serialization round-trips, and individual similarity helpers.
"""
from __future__ import annotations

import pytest

from src.learning.element_fingerprint import (
    ElementFingerprint,
    FingerprintMatch,
    _class_list_similarity,
    _text_similarity,
    compute_fingerprint,
    deserialize_fingerprint,
    find_best_match,
    score_similarity,
    serialize_fingerprint,
)

# ── Fixtures / Helpers ──────────────────────────────


def _make_button_fp(
    text: str = "Submit",
    class_list: tuple[str, ...] = ("btn", "btn-primary"),
    nearby_text: str = "Please submit the form",
    bbox: tuple[int, int, int, int] = (100, 200, 80, 40),
    attributes: dict[str, str] | None = None,
) -> ElementFingerprint:
    """Create a typical button fingerprint for reuse across tests."""
    return compute_fingerprint(
        tag="button",
        role="button",
        text=text,
        class_list=class_list,
        nearby_text=nearby_text,
        bbox=bbox,
        attributes=attributes or {"type": "submit", "data-testid": "submit-btn"},
    )


# ── Tests ───────────────────────────────────────────


def test_basic_fingerprint_creation() -> None:
    """compute_fingerprint returns correct ElementFingerprint with all fields set."""
    fp = compute_fingerprint(
        tag="input",
        role="textbox",
        text="",
        class_list=["form-control", "input-lg"],
        nearby_text="Enter your email",
        bbox=(50, 100, 200, 30),
        attributes={"type": "email", "name": "email"},
    )

    assert fp.tag == "input"
    assert fp.role == "textbox"
    assert fp.text == ""
    assert fp.class_list == ("form-control", "input-lg")
    assert fp.nearby_text == "Enter your email"
    assert fp.bbox == (50, 100, 200, 30)
    assert len(fp.attributes_hash) == 16  # SHA-256 truncated to 16 hex chars


def test_attributes_hash_deterministic() -> None:
    """Same attributes (regardless of insertion order) produce the same hash."""
    attrs_a = {"type": "submit", "data-testid": "btn", "class": "primary"}
    attrs_b = {"class": "primary", "data-testid": "btn", "type": "submit"}

    fp_a = compute_fingerprint(tag="button", attributes=attrs_a)
    fp_b = compute_fingerprint(tag="button", attributes=attrs_b)

    assert fp_a.attributes_hash == fp_b.attributes_hash
    assert len(fp_a.attributes_hash) == 16


def test_identical_fingerprints_score_1() -> None:
    """Identical fingerprints should yield a similarity score of 1.0."""
    fp = _make_button_fp()
    score = score_similarity(fp, fp)
    assert score == pytest.approx(1.0)


def test_completely_different_score_near_0() -> None:
    """Completely different fingerprints should score near 0.0."""
    fp1 = compute_fingerprint(
        tag="button",
        role="button",
        text="Submit",
        class_list=("btn", "btn-primary"),
        nearby_text="Please submit the form",
        bbox=(100, 200, 80, 40),
        attributes={"type": "submit"},
    )
    fp2 = compute_fingerprint(
        tag="input",
        role="textbox",
        text="Search here",
        class_list=("search-box", "large"),
        nearby_text="Find products",
        bbox=(500, 10, 300, 25),
        attributes={"type": "search"},
    )

    score = score_similarity(fp1, fp2)
    assert score < 0.2


def test_partial_match_intermediate() -> None:
    """Partial match (same tag/role, different text) should score between 0.3 and 0.8."""
    fp1 = compute_fingerprint(
        tag="button",
        role="button",
        text="Submit Order",
        class_list=("btn", "btn-primary"),
        nearby_text="Complete your purchase",
        bbox=(100, 200, 80, 40),
    )
    fp2 = compute_fingerprint(
        tag="button",
        role="button",
        text="Cancel Order",
        class_list=("btn", "btn-danger"),
        nearby_text="Go back to cart",
        bbox=(200, 200, 80, 40),
    )

    score = score_similarity(fp1, fp2)
    assert 0.3 < score < 0.8


def test_custom_weights() -> None:
    """Custom weights should change the resulting score."""
    fp1 = compute_fingerprint(tag="button", text="Submit", role="button")
    fp2 = compute_fingerprint(tag="button", text="Cancel", role="button")

    # Default weights: text has weight 0.25, so text mismatch matters.
    score_default = score_similarity(fp1, fp2)

    # Custom: text weight = 0.0, tag/role only matter.
    custom_weights = {"tag": 0.50, "role": 0.50, "text": 0.0}
    score_custom = score_similarity(fp1, fp2, weights=custom_weights)

    assert score_custom > score_default
    assert score_custom == pytest.approx(1.0)


def test_text_similarity_fuzzy() -> None:
    """Similar text should produce a high (but not 1.0) similarity score."""
    sim = _text_similarity("Submit", "Submit Form")
    # SequenceMatcher ratio for "submit" vs "submit form" should be > 0.6
    assert sim > 0.6
    assert sim < 1.0


def test_find_best_above_threshold() -> None:
    """find_best_match returns the best candidate above the threshold."""
    reference = _make_button_fp(text="Submit")

    candidates = [
        ("eid-1", compute_fingerprint(tag="div", text="Footer")),
        ("eid-2", _make_button_fp(text="Submit")),  # near-identical
        ("eid-3", compute_fingerprint(tag="a", text="Link")),
    ]

    match = find_best_match(reference, candidates, threshold=0.6)

    assert match is not None
    assert isinstance(match, FingerprintMatch)
    assert match.matched_eid == "eid-2"
    assert match.score > 0.9
    assert "tag" in match.breakdown
    assert "text" in match.breakdown


def test_find_none_below_threshold() -> None:
    """find_best_match returns None when no candidate exceeds the threshold."""
    reference = _make_button_fp(text="Submit")

    candidates = [
        ("eid-1", compute_fingerprint(tag="div", text="Footer", role="contentinfo")),
        ("eid-2", compute_fingerprint(tag="span", text="Copyright 2024")),
    ]

    match = find_best_match(reference, candidates, threshold=0.8)

    assert match is None


def test_empty_candidates() -> None:
    """find_best_match returns None for an empty candidate list."""
    reference = _make_button_fp()
    match = find_best_match(reference, [], threshold=0.5)
    assert match is None


def test_round_trip_serialize() -> None:
    """Serializing then deserializing should produce an equivalent fingerprint."""
    original = _make_button_fp(
        text="Sign In",
        class_list=("auth-btn", "large"),
        nearby_text="Welcome back",
        bbox=(10, 20, 120, 44),
        attributes={"type": "submit", "form": "login-form"},
    )

    data = serialize_fingerprint(original)
    restored = deserialize_fingerprint(data)

    assert restored == original
    assert isinstance(data["class_list"], list)
    assert isinstance(data["bbox"], list)


def test_class_list_jaccard() -> None:
    """Jaccard similarity for class lists should reflect set overlap."""
    # Identical class lists.
    assert _class_list_similarity(("a", "b", "c"), ("a", "b", "c")) == pytest.approx(1.0)

    # Completely disjoint.
    assert _class_list_similarity(("a", "b"), ("c", "d")) == pytest.approx(0.0)

    # Partial overlap: {"a","b","c"} & {"b","c","d"} = {"b","c"}, union = {"a","b","c","d"}.
    assert _class_list_similarity(("a", "b", "c"), ("b", "c", "d")) == pytest.approx(0.5)

    # Both empty.
    assert _class_list_similarity((), ()) == pytest.approx(1.0)

    # One empty.
    assert _class_list_similarity(("a",), ()) == pytest.approx(0.0)
