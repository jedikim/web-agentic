"""Tests for src.learning.plan_cache -- adaptive plan caching with fuzzy matching."""
from __future__ import annotations

from src.learning.plan_cache import (
    AdaptedStep,
    adapt_cached_plan,
    extract_keywords,
    keyword_similarity,
)


class TestExtractKeywords:
    def test_basic_english_extraction(self) -> None:
        """Extracts meaningful keywords from an English intent."""
        result = extract_keywords("search for shoes on Amazon")
        assert result.keywords == frozenset({"search", "shoes", "amazon"})
        assert result.raw_intent == "search for shoes on Amazon"

    def test_korean_extraction(self) -> None:
        """Extracts keywords from a Korean intent, removing stop words."""
        result = extract_keywords("\uc544\ub9c8\uc874\uc5d0\uc11c \uc2e0\ubc1c \uac80\uc0c9")
        # "\uc5d0\uc11c" is a Korean stop word but "\uc544\ub9c8\uc874\uc5d0\uc11c" is one token
        assert "\uc2e0\ubc1c" in result.keywords
        assert "\uac80\uc0c9" in result.keywords

    def test_stop_words_removed(self) -> None:
        """English stop words like 'the', 'to', 'and' are removed."""
        result = extract_keywords("go to the website and click the button")
        assert "the" not in result.keywords
        assert "to" not in result.keywords
        assert "and" not in result.keywords
        # Meaningful words remain
        assert "go" in result.keywords
        assert "website" in result.keywords
        assert "click" in result.keywords
        assert "button" in result.keywords

    def test_short_tokens_removed(self) -> None:
        """Single-character tokens are filtered out."""
        result = extract_keywords("go to a b c website")
        # 'a' is a stop word AND short; 'b', 'c' are single chars
        assert "a" not in result.keywords
        assert "b" not in result.keywords
        assert "c" not in result.keywords

    def test_empty_intent(self) -> None:
        """Empty string returns empty keyword set."""
        result = extract_keywords("")
        assert result.keywords == frozenset()

        result_spaces = extract_keywords("   ")
        assert result_spaces.keywords == frozenset()


class TestKeywordSimilarity:
    def test_identical_keywords_score_1(self) -> None:
        """Same keyword sets yield similarity of 1.0."""
        kw = frozenset({"search", "shoes", "amazon"})
        assert keyword_similarity(kw, kw) == 1.0

    def test_disjoint_keywords_score_0(self) -> None:
        """Non-overlapping keyword sets yield similarity of 0.0."""
        kw1 = frozenset({"search", "shoes"})
        kw2 = frozenset({"navigate", "login"})
        assert keyword_similarity(kw1, kw2) == 0.0

    def test_partial_overlap(self) -> None:
        """Partially overlapping sets yield intermediate score."""
        kw1 = frozenset({"search", "shoes", "amazon"})
        kw2 = frozenset({"search", "bags", "amazon"})
        # intersection = {"search", "amazon"} (2), union = {"search", "shoes", "amazon", "bags"} (4)
        sim = keyword_similarity(kw1, kw2)
        assert sim == 2.0 / 4.0
        assert 0.0 < sim < 1.0

    def test_both_empty_returns_zero(self) -> None:
        """Two empty sets return 0.0."""
        assert keyword_similarity(frozenset(), frozenset()) == 0.0

    def test_one_empty_returns_zero(self) -> None:
        """One empty set returns 0.0."""
        kw = frozenset({"search"})
        assert keyword_similarity(kw, frozenset()) == 0.0
        assert keyword_similarity(frozenset(), kw) == 0.0


class TestAdaptCachedPlan:
    def test_no_adaptation_needed(self) -> None:
        """Identical intents produce adapted=False for all steps."""
        steps = [
            {"step_id": "s1", "intent": "search shoes", "arguments": ["shoes"]},
        ]
        result = adapt_cached_plan(steps, "search shoes on amazon", "search shoes on amazon")
        assert result is not None
        assert len(result) == 1
        assert result[0].adapted is False
        assert result[0].arguments == ("shoes",)

    def test_argument_replacement(self) -> None:
        """Different arguments in intents cause replacement in step args."""
        steps = [
            {"step_id": "s1", "intent": "search shoes", "arguments": ["shoes"]},
            {"step_id": "s2", "intent": "click result", "arguments": []},
        ]
        result = adapt_cached_plan(
            steps,
            original_intent="search shoes on amazon",
            current_intent="search bags on amazon",
        )
        assert result is not None
        # "shoes" replaced with "bags"
        assert result[0].arguments == ("bags",)
        assert result[0].adapted is True
        # s2 has no args with "shoes" so not adapted
        assert result[1].adapted is False

    def test_marks_adapted_steps(self) -> None:
        """Steps with replaced arguments have adapted=True."""
        steps = [
            {"step_id": "s1", "intent": "type shoes", "arguments": ["shoes"]},
            {"step_id": "s2", "intent": "click submit", "arguments": ["submit"]},
        ]
        result = adapt_cached_plan(
            steps,
            original_intent="search shoes",
            current_intent="search bags",
        )
        assert result is not None
        # s1 intent and arg contain "shoes" -> replaced
        adapted_flags = [s.adapted for s in result]
        assert adapted_flags[0] is True
        # s2 has no "shoes" reference -> not adapted
        assert adapted_flags[1] is False

    def test_completely_different_no_adapt(self) -> None:
        """Very different intents (sim < 0.3) return None."""
        steps = [
            {"step_id": "s1", "intent": "search shoes", "arguments": ["shoes"]},
        ]
        result = adapt_cached_plan(
            steps,
            original_intent="search shoes on amazon",
            current_intent="login to gmail account",
        )
        assert result is None

    def test_step_id_fallback(self) -> None:
        """Steps without step_id get auto-generated IDs."""
        steps = [
            {"intent": "click button", "arguments": []},
        ]
        result = adapt_cached_plan(steps, "click button", "click button")
        assert result is not None
        assert result[0].step_id == "step_0"

    def test_adapted_step_dataclass(self) -> None:
        """AdaptedStep is a frozen dataclass with correct defaults."""
        step = AdaptedStep(step_id="s1", intent="test")
        assert step.node_type == "action"
        assert step.selector is None
        assert step.arguments == ()
        assert step.adapted is False
