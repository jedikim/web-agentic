"""Stage 2 vector ranker — hnswlib semantic search for candidate elements.

Builds a per-page ephemeral hnswlib index, embeds candidates + intent,
runs knn_query, and returns the top-k most semantically relevant elements.
Index is discarded immediately after search (no persistence).

Requires the ``embeddings`` optional dependency group::

    pip install -e ".[embeddings]"
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.core.types import ExtractedElement

logger = logging.getLogger(__name__)


@runtime_checkable
class IEmbedder(Protocol):
    """Embedding provider protocol."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


class FastEmbedProvider:
    """ONNX-based local embedding using fastembed.

    Uses a multilingual MiniLM model (384-dim) optimized for CPU.
    Model is loaded lazily on first embed_batch() call.

    Args:
        model_name: HuggingFace model ID for fastembed.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        self._model_name = model_name
        self._model: object | None = None
        self._dim: int = 384

    def _ensure_model(self) -> object:
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError(
                    "fastembed is required for vector ranking. "
                    "Install with: pip install -e '.[embeddings]'"
                ) from exc
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats).
        """
        model = self._ensure_model()
        # fastembed returns a generator of numpy arrays
        embeddings = list(model.embed(texts))  # type: ignore[attr-defined]
        return [emb.tolist() for emb in embeddings]

    @property
    def dimension(self) -> int:
        """Embedding dimension (384 for MiniLM)."""
        return self._dim


def _element_to_text(el: ExtractedElement) -> str:
    """Convert an element to a searchable text representation.

    Format: "{type} {role} {text} {parent_context}"
    """
    parts: list[str] = [el.type]
    if el.role:
        parts.append(el.role)
    if el.text:
        parts.append(el.text)
    if el.parent_context:
        parts.append(el.parent_context)
    return " ".join(parts)


@dataclass(frozen=True)
class VectorRankResult:
    """Result of vector ranking.

    Attributes:
        candidates: Ranked candidates (closest to intent first).
        distances: Cosine distances for each candidate.
    """

    candidates: list[ExtractedElement]
    distances: list[float] = field(default_factory=list)


class VectorRanker:
    """Per-page ephemeral hnswlib vector search.

    Builds a temporary index for each rank() call:
    1. Convert elements → text
    2. Batch embed (candidates + intent)
    3. Build hnswlib index
    4. knn_query with intent vector
    5. Return top-k, discard index

    Args:
        embedder: Embedding provider (defaults to FastEmbedProvider).
    """

    def __init__(self, embedder: IEmbedder | None = None) -> None:
        self._embedder = embedder or FastEmbedProvider()

    async def rank(
        self,
        candidates: Sequence[ExtractedElement],
        intent: str,
        top_k: int = 10,
    ) -> list[ExtractedElement]:
        """Rank candidates by semantic similarity to intent.

        Args:
            candidates: Pre-filtered DOM elements from Stage 1.
            intent: User intent string.
            top_k: Number of top results to return.

        Returns:
            Top-k candidates sorted by semantic similarity.
        """
        if not candidates:
            return []

        top_k = min(top_k, len(candidates))

        try:
            import hnswlib  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "hnswlib is required for vector ranking. "
                "Install with: pip install -e '.[embeddings]'"
            ) from exc

        # 1. Convert to text
        texts = [_element_to_text(el) for el in candidates]

        # 2. Embed all texts + intent in one batch
        all_texts = texts + [intent]
        all_embeddings = self._embedder.embed_batch(all_texts)
        candidate_embeddings = all_embeddings[:-1]
        intent_embedding = all_embeddings[-1]

        # 3. Build ephemeral hnswlib index
        dim = self._embedder.dimension
        n = len(candidate_embeddings)
        index = hnswlib.Index(space="cosine", dim=dim)
        index.init_index(max_elements=n, ef_construction=100, M=16)
        index.add_items(candidate_embeddings, list(range(n)))
        index.set_ef(max(top_k * 2, 50))

        # 4. Query
        labels, distances = index.knn_query([intent_embedding], k=top_k)

        # 5. Collect results
        cand_list = list(candidates)
        result: list[ExtractedElement] = []
        for idx in labels[0]:
            result.append(cand_list[int(idx)])

        logger.debug(
            "Vector rank: %d candidates → top %d (distances: %s)",
            n, len(result), [f"{d:.3f}" for d in distances[0][:5]],
        )

        return result
