"""Multilingual text matcher — keyword_weights scoring for DOM nodes.

Implements the Prune4Web approach: score DOM node text against keyword_weights
from the Planner. Supports multilingual text matching:
- CJK (Korean, Japanese, Chinese): character-level substring matching
- European + Arabic (30 languages): Snowball stemmed matching

Dependencies:
- snowballstemmer (pure Python, always available)
- mecab-python3 (Korean tokenization, optional)
- fugashi (Japanese tokenization, optional)
- jieba (Chinese tokenization, optional)
"""

from __future__ import annotations

import re
from typing import Any

from src.core.types import DOMNode, ScoredNode

# CJK Unicode ranges
_CJK_RANGES = (
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0xAC00, 0xD7AF),   # Hangul Syllables
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
)


def _is_cjk_char(char: str) -> bool:
    """Check if a character is CJK."""
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def _has_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return any(_is_cjk_char(c) for c in text)


def _detect_language(text: str) -> str:
    """Simple language detection based on character analysis.

    Returns:
        'ko' for Korean, 'ja' for Japanese, 'zh' for Chinese, 'en' for others.
    """
    hangul_count = 0
    kana_count = 0
    cjk_ideograph_count = 0
    total = 0

    for char in text:
        code = ord(char)
        if char.isalpha() or _is_cjk_char(char):
            total += 1
            if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
                hangul_count += 1
            elif 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
                kana_count += 1
            elif 0x4E00 <= code <= 0x9FFF:
                cjk_ideograph_count += 1

    if total == 0:
        return "en"
    if hangul_count / total > 0.3:
        return "ko"
    if kana_count / total > 0.1:
        return "ja"
    if cjk_ideograph_count / total > 0.3:
        return "zh"
    return "en"


class TextMatcher:
    """Score DOM nodes against keyword_weights using multilingual matching.

    Usage:
        matcher = TextMatcher()
        score = matcher.score(node, {"검색": 1.0, "search": 0.8})
    """

    def __init__(self) -> None:
        self._stemmers: dict[str, Any] = {}
        self._ko_tokenizer: Any | None = None
        self._ja_tokenizer: Any | None = None
        self._zh_tokenize: Any | None = None
        self._init_done = False

    def _lazy_init(self) -> None:
        """Lazy-initialize stemmers and tokenizers."""
        if self._init_done:
            return
        self._init_done = True

        # Snowball stemmers for European languages
        try:
            import contextlib

            import snowballstemmer  # type: ignore[import-untyped]
            for lang in ("english", "korean"):
                with contextlib.suppress(Exception):
                    self._stemmers[lang] = snowballstemmer.stemmer(lang)
            # Default English stemmer
            if "english" not in self._stemmers:
                self._stemmers["english"] = snowballstemmer.stemmer("english")
        except ImportError:
            pass

        # Korean tokenizer (mecab)
        try:
            import MeCab  # type: ignore[import-not-found]
            self._ko_tokenizer = MeCab.Tagger("-Owakati")
        except ImportError:
            pass

        # Japanese tokenizer (fugashi)
        try:
            import fugashi  # type: ignore[import-not-found]
            self._ja_tokenizer = fugashi.Tagger("-Owakati")
        except ImportError:
            pass

        # Chinese tokenizer (jieba)
        try:
            import jieba  # type: ignore[import-not-found]
            self._zh_tokenize = jieba.cut
        except ImportError:
            pass

    def score(self, node: DOMNode, keyword_weights: dict[str, float]) -> float:
        """Score a DOM node against keyword weights.

        Combines node text, attribute values, AX name, and AX role
        into a single text blob, then matches each keyword.

        Args:
            node: DOM node to score.
            keyword_weights: Mapping of keyword -> weight.

        Returns:
            Weighted sum of matching keywords.
        """
        self._lazy_init()

        # Combine all text sources
        parts: list[str] = []
        if node.text:
            parts.append(node.text)
        if node.ax_name:
            parts.append(node.ax_name)
        if node.ax_role:
            parts.append(node.ax_role)
        for val in node.attrs.values():
            if val:
                parts.append(val)

        combined = " ".join(parts).lower()
        if not combined.strip():
            return 0.0

        total = 0.0
        for keyword, weight in keyword_weights.items():
            if self._match(combined, keyword.lower()):
                total += weight

        return total

    def _match(self, text: str, keyword: str) -> bool:
        """Check if keyword matches within text.

        CJK: substring matching (character-level).
        European: tries exact substring first, then stemmed matching.
        """
        # Always try exact substring first (works for all languages)
        if keyword in text:
            return True

        # CJK: substring is sufficient; also try without spaces
        if _has_cjk(keyword):
            # Remove spaces and try again
            text_nospace = text.replace(" ", "")
            keyword_nospace = keyword.replace(" ", "")
            if keyword_nospace in text_nospace:
                return True

            # For Korean, try tokenized matching if tokenizer available
            lang = _detect_language(keyword)
            if lang == "ko" and self._ko_tokenizer is not None:
                return self._tokenized_match(text, keyword, "ko")
            if lang == "ja" and self._ja_tokenizer is not None:
                return self._tokenized_match(text, keyword, "ja")
            if lang == "zh" and self._zh_tokenize is not None:
                return self._tokenized_match(text, keyword, "zh")

            return False

        # European: try stemmed matching
        return self._stemmed_match(text, keyword)

    def _stemmed_match(self, text: str, keyword: str) -> bool:
        """Match using Snowball stemming for European languages."""
        stemmer = self._stemmers.get("english")
        if stemmer is None:
            return False

        # Stem the keyword
        keyword_stems = set(stemmer.stemWords(keyword.split()))
        if not keyword_stems:
            return False

        # Stem words in text and check for overlap
        text_words = re.findall(r"[a-zA-Z]+", text)
        text_stems = set(stemmer.stemWords(text_words))

        return bool(keyword_stems & text_stems)

    def _tokenized_match(self, text: str, keyword: str, lang: str) -> bool:
        """Match using language-specific tokenization."""
        text_tokens = self._tokenize(text, lang)
        keyword_tokens = self._tokenize(keyword, lang)

        if not keyword_tokens:
            return False

        # Check if all keyword tokens appear in text tokens
        text_token_set = set(text_tokens)
        return all(kt in text_token_set for kt in keyword_tokens)

    def _tokenize(self, text: str, lang: str) -> list[str]:
        """Tokenize text using language-specific tokenizer."""
        if lang == "ko" and self._ko_tokenizer is not None:
            try:
                result = self._ko_tokenizer.parse(text)
                if result:
                    return [t for t in result.strip().split() if len(t) > 1]
            except Exception:
                pass
        elif lang == "ja" and self._ja_tokenizer is not None:
            try:
                result = self._ja_tokenizer.parse(text)
                if result:
                    return [t for t in result.strip().split() if len(t) > 1]
            except Exception:
                pass
        elif lang == "zh" and self._zh_tokenize is not None:
            try:
                return [t for t in self._zh_tokenize(text) if len(t) > 1]
            except Exception:
                pass

        # Fallback: simple whitespace split
        return [w for w in text.split() if len(w) > 1]

    def filter_nodes(
        self,
        nodes: list[DOMNode],
        keyword_weights: dict[str, float],
        top_k: int = 20,
    ) -> list[ScoredNode]:
        """Score and filter nodes, returning top-K by score.

        Args:
            nodes: List of DOM nodes to filter.
            keyword_weights: Mapping of keyword -> weight.
            top_k: Maximum number of results to return.

        Returns:
            Top-K scored nodes, sorted by score descending.
        """
        scored: list[ScoredNode] = []
        for node in nodes:
            s = self.score(node, keyword_weights)
            if s > 0:
                scored.append(ScoredNode(node=node, score=s))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
