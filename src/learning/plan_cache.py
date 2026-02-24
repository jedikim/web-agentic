"""Adaptive plan caching -- keyword-based fuzzy matching for execution plan reuse.

When exact intent matching fails, extracts keywords from intents and uses
Jaccard similarity to find similar cached plans. Adapted plans have arguments
replaced based on intent differences.

Based on adaptive plan caching research (NeurIPS 2025).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# -- Stop Words ---------------------------------------------------------------

_STOP_WORDS_EN: frozenset[str] = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with",
    "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "this", "that", "it", "its", "i", "me",
    "my", "we", "our", "you", "your", "he", "she", "they", "them",
    "from", "by", "as", "if", "not", "no", "so", "up", "out",
    "then", "than", "too", "very", "just", "about", "into",
})

_STOP_WORDS_KO: frozenset[str] = frozenset({
    "\uc744", "\ub97c", "\uc774", "\uac00", "\uc740", "\ub294", "\uc758", "\uc5d0", "\uc5d0\uc11c",
    "\ub85c", "\uc73c\ub85c", "\uc640", "\uacfc", "\ub3c4", "\ub9cc", "\uae4c\uc9c0",
    "\ubd80\ud130",
    "\uc5d0\uac8c", "\ud55c\ud14c", "\uaed8", "\ud558\uace0", "\ub77c\uace0", "\ub2e4\uace0",
})


# -- Data Types ---------------------------------------------------------------

@dataclass(frozen=True)
class ExtractedKeywords:
    """Result of keyword extraction from an intent string.

    Attributes:
        keywords: Set of extracted meaningful keywords.
        raw_intent: The original intent string.
    """

    keywords: frozenset[str]
    raw_intent: str


@dataclass(frozen=True)
class PlanMatch:
    """Result of a fuzzy plan cache lookup.

    Attributes:
        similarity: Jaccard similarity score in [0.0, 1.0].
        cached_steps: The cached execution steps.
        original_intent: The intent that produced the cached steps.
        needs_adaptation: Whether argument replacement is needed.
    """

    similarity: float
    cached_steps: list[object]
    original_intent: str
    needs_adaptation: bool


@dataclass(frozen=True)
class AdaptedStep:
    """A single step after adaptation.

    Attributes:
        step_id: Unique step identifier.
        intent: Step-level intent description.
        node_type: Step type (e.g. "action", "navigation").
        selector: Optional CSS/XPath selector.
        arguments: List of argument strings.
        adapted: Whether this step was modified during adaptation.
    """

    step_id: str
    intent: str
    node_type: str = "action"
    selector: str | None = None
    arguments: tuple[str, ...] = ()
    adapted: bool = False


# -- Internal Helpers ---------------------------------------------------------

def _extract_argument_diff(
    original_intent: str,
    current_intent: str,
    original_kw: frozenset[str],
    current_kw: frozenset[str],
) -> dict[str, str]:
    """Find words in current intent that replace words in original.

    Returns a mapping of original_word -> replacement_word for words
    that differ between the intents.

    Args:
        original_intent: The intent that produced the cached steps.
        current_intent: The current intent to adapt for.
        original_kw: Keywords from original intent.
        current_kw: Keywords from current intent.

    Returns:
        Mapping of original_word to replacement_word.
    """
    only_in_original = original_kw - current_kw
    only_in_current = current_kw - original_kw

    replacements: dict[str, str] = {}
    # Simple 1:1 mapping when counts match
    if len(only_in_original) == len(only_in_current) and len(only_in_original) > 0:
        orig_list = sorted(only_in_original)
        curr_list = sorted(only_in_current)
        for o, c in zip(orig_list, curr_list, strict=True):
            replacements[o] = c
    elif only_in_original and only_in_current:
        # Best-effort: map first available
        orig_list = sorted(only_in_original)
        curr_list = sorted(only_in_current)
        for i, o in enumerate(orig_list):
            if i < len(curr_list):
                replacements[o] = curr_list[i]

    return replacements


# -- Public API ---------------------------------------------------------------

def extract_keywords(intent: str) -> ExtractedKeywords:
    """Extract meaningful keywords from an intent string.

    Removes stop words (English and Korean), short tokens (length <= 1),
    and normalizes to lowercase.

    Args:
        intent: Natural language intent string.

    Returns:
        ExtractedKeywords with the filtered keyword set.
    """
    if not intent or not intent.strip():
        return ExtractedKeywords(keywords=frozenset(), raw_intent=intent)

    # Tokenize: split on whitespace and common punctuation
    tokens = re.findall(r"[a-zA-Z\uac00-\ud7a3\u0030-\u0039]+", intent.lower())

    # Filter stop words and short tokens
    keywords = frozenset(
        t for t in tokens
        if t not in _STOP_WORDS_EN
        and t not in _STOP_WORDS_KO
        and len(t) > 1
    )

    return ExtractedKeywords(keywords=keywords, raw_intent=intent)


def keyword_similarity(kw1: frozenset[str], kw2: frozenset[str]) -> float:
    """Compute Jaccard similarity between two keyword sets.

    Args:
        kw1: First keyword set.
        kw2: Second keyword set.

    Returns:
        Jaccard index in [0.0, 1.0]. Returns 0.0 if both sets are empty.
    """
    if not kw1 and not kw2:
        return 0.0
    if not kw1 or not kw2:
        return 0.0
    intersection = kw1 & kw2
    union = kw1 | kw2
    return len(intersection) / len(union)


def adapt_cached_plan(
    cached_steps: list[dict[str, Any]],
    original_intent: str,
    current_intent: str,
) -> list[AdaptedStep] | None:
    """Adapt a cached plan's arguments for a new but similar intent.

    Extracts keyword differences between original and current intent,
    then replaces matching arguments in cached steps.

    Args:
        cached_steps: List of step dicts from cache.
        original_intent: The intent that produced the cached steps.
        current_intent: The current intent to adapt for.

    Returns:
        List of AdaptedStep, or None if intents are too different.
    """
    orig_kw = extract_keywords(original_intent)
    curr_kw = extract_keywords(current_intent)

    sim = keyword_similarity(orig_kw.keywords, curr_kw.keywords)
    if sim < 0.3:
        return None

    replacements = _extract_argument_diff(
        original_intent, current_intent,
        orig_kw.keywords, curr_kw.keywords,
    )

    adapted_steps: list[AdaptedStep] = []
    for i, step in enumerate(cached_steps):
        step_intent = str(step.get("intent", ""))
        args = list(step.get("arguments", []))
        was_adapted = False

        # Apply argument replacements
        new_args: list[str] = []
        for arg in args:
            new_arg = str(arg)
            for old_word, new_word in replacements.items():
                if old_word in new_arg.lower():
                    new_arg = re.sub(
                        re.escape(old_word), new_word, new_arg, flags=re.IGNORECASE,
                    )
                    was_adapted = True
            new_args.append(new_arg)

        # Also adapt step intent text
        new_intent = step_intent
        for old_word, new_word in replacements.items():
            if old_word in new_intent.lower():
                new_intent = re.sub(
                    re.escape(old_word), new_word, new_intent, flags=re.IGNORECASE,
                )
                was_adapted = True

        adapted_steps.append(AdaptedStep(
            step_id=str(step.get("step_id", f"step_{i}")),
            intent=new_intent,
            node_type=str(step.get("node_type", "action")),
            selector=step.get("selector"),
            arguments=tuple(new_args),
            adapted=was_adapted,
        ))

    return adapted_steps
