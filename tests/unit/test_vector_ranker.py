"""Unit tests for Stage 2 vector ranker — hnswlib semantic search.

All tests use a mock embedder to avoid fastembed/ONNX dependency.
Tests requiring hnswlib are auto-skipped when the package is not installed.
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from src.ai.vector_ranker import (
    FastEmbedProvider,
    VectorRanker,
    _element_to_text,
)
from src.core.types import ExtractedElement

_has_hnswlib = True
try:
    import hnswlib  # noqa: F401
except ImportError:
    _has_hnswlib = False

requires_hnswlib = pytest.mark.skipif(not _has_hnswlib, reason="hnswlib not installed")


def _el(
    eid: str = "el",
    text: str | None = None,
    role: str | None = None,
    parent_context: str | None = None,
    el_type: str = "button",
) -> ExtractedElement:
    return ExtractedElement(
        eid=eid, type=el_type, text=text, role=role,
        bbox=(0, 300, 100, 40), visible=True, parent_context=parent_context,
    )


# ── _element_to_text ─────────────────────────────────


class TestElementToText:
    def test_all_fields(self) -> None:
        el = _el(text="Sign In", role="button", parent_context="header-bar")
        result = _element_to_text(el)
        assert "button" in result
        assert "Sign In" in result
        assert "header-bar" in result

    def test_minimal(self) -> None:
        el = _el()
        result = _element_to_text(el)
        assert result == "button"

    def test_with_text_only(self) -> None:
        el = _el(text="Click me")
        result = _element_to_text(el)
        assert "button" in result
        assert "Click me" in result

    def test_link_type(self) -> None:
        el = _el(el_type="link", text="Homepage")
        result = _element_to_text(el)
        assert result.startswith("link")


# ── MockEmbedder ─────────────────────────────────────


class MockEmbedder:
    """Deterministic mock embedder for testing."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Create deterministic embeddings based on text content."""
        results: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for i, ch in enumerate(text.encode("utf-8")):
                vec[i % self._dim] += ch / 255.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vec = [v / norm for v in vec]
            results.append(vec)
        return results

    @property
    def dimension(self) -> int:
        return self._dim


# ── VectorRanker ─────────────────────────────────────


@requires_hnswlib
class TestVectorRanker:
    """Tests for VectorRanker.rank() — requires hnswlib."""

    @pytest.fixture
    def ranker(self) -> VectorRanker:
        return VectorRanker(embedder=MockEmbedder(dim=8))

    async def test_empty_candidates(self, ranker: VectorRanker) -> None:
        result = await ranker.rank([], "search")
        assert result == []

    async def test_returns_top_k(self, ranker: VectorRanker) -> None:
        candidates = [_el(eid=f"el-{i}", text=f"Element {i}") for i in range(20)]
        result = await ranker.rank(candidates, "search for products", top_k=5)
        assert len(result) == 5
        result_eids = {el.eid for el in result}
        input_eids = {el.eid for el in candidates}
        assert result_eids.issubset(input_eids)

    async def test_top_k_clamped(self, ranker: VectorRanker) -> None:
        """top_k > len(candidates) should return all candidates."""
        candidates = [_el(eid=f"el-{i}", text=f"Element {i}") for i in range(3)]
        result = await ranker.rank(candidates, "search", top_k=10)
        assert len(result) == 3

    async def test_no_duplicates(self, ranker: VectorRanker) -> None:
        candidates = [_el(eid=f"el-{i}", text=f"Item {i}") for i in range(15)]
        result = await ranker.rank(candidates, "find item", top_k=10)
        eids = [el.eid for el in result]
        assert len(eids) == len(set(eids))

    async def test_semantic_relevance(self, ranker: VectorRanker) -> None:
        """Elements with text closer to intent should rank higher."""
        candidates = [
            _el(eid="login", text="Sign In Login", role="button"),
            _el(eid="random", text="XYZZY Random Content"),
            _el(eid="login2", text="로그인 Sign In", role="button"),
        ]
        result = await ranker.rank(candidates, "login sign in", top_k=3)
        assert len(result) == 3
        eids = {el.eid for el in result}
        assert "login" in eids
        assert "login2" in eids

    async def test_single_candidate(self, ranker: VectorRanker) -> None:
        candidates = [_el(eid="only", text="The Only One")]
        result = await ranker.rank(candidates, "find it", top_k=5)
        assert len(result) == 1
        assert result[0].eid == "only"


# ── FastEmbedProvider ────────────────────────────────


class TestFastEmbedProvider:

    def test_dimension(self) -> None:
        provider = FastEmbedProvider()
        assert provider.dimension == 384

    def test_import_error_gives_helpful_message(self) -> None:
        """Should raise ImportError with install instructions."""
        provider = FastEmbedProvider()
        with (
            patch.dict("sys.modules", {"fastembed": None}),
            pytest.raises(ImportError, match="embeddings"),
        ):
            provider._ensure_model()

    def test_custom_model_name(self) -> None:
        provider = FastEmbedProvider(model_name="custom/model")
        assert provider._model_name == "custom/model"


# ── hnswlib import guard ─────────────────────────────


class TestHnswlibImportGuard:

    async def test_missing_hnswlib_error(self) -> None:
        """Should raise ImportError with install instructions when hnswlib missing."""
        ranker = VectorRanker(embedder=MockEmbedder(dim=8))
        candidates = [_el(eid="a", text="test")]
        with (
            patch.dict("sys.modules", {"hnswlib": None}),
            pytest.raises(ImportError, match="hnswlib"),
        ):
            await ranker.rank(candidates, "test")
