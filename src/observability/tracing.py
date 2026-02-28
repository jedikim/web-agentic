"""Langfuse tracing (v3 SDK) — env-based on/off with no-op fallback.

Enable tracing by setting environment variables::

    LANGFUSE_ENABLED=true
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_BASE_URL=https://langfuse.jedi.team

When ``LANGFUSE_ENABLED`` is not ``true`` or ``langfuse`` is not installed,
all decorators become transparent no-ops with zero overhead.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_ENABLED = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
_observe: Any = None
_get_client: Any = None

if _ENABLED:
    try:
        from langfuse import get_client as _lf_get_client  # type: ignore[import-not-found]
        from langfuse import observe as _lf_observe

        _observe = _lf_observe
        _get_client = _lf_get_client
        # Eagerly initialize the singleton client so env vars are validated
        _get_client()
        logger.info(
            "Langfuse tracing enabled (base_url=%s)",
            os.environ.get("LANGFUSE_BASE_URL"),
        )
    except ImportError:
        logger.warning(
            "LANGFUSE_ENABLED=true but langfuse not installed — tracing disabled",
        )
        _ENABLED = False


def is_enabled() -> bool:
    """Return whether Langfuse tracing is active."""
    return _ENABLED


# ── trace decorator ──────────────────────────────────


def trace(**kwargs: Any) -> Callable[[F], F]:
    """Decorator that traces a function via Langfuse ``@observe``.

    When tracing is disabled, returns the original function unchanged.
    Supports both sync and async functions.

    Args:
        **kwargs: Passed to ``langfuse.observe()`` — e.g.
            ``name="llm-select"``, ``as_type="generation"``.
    """
    if _ENABLED and _observe is not None:
        return _observe(**kwargs)  # type: ignore[no-any-return]

    # No-op: return original function as-is (zero overhead)
    def _noop(fn: F) -> F:
        return fn

    return _noop


# ── context helpers ──────────────────────────────────


def update_current_observation(**kwargs: Any) -> None:
    """Update the current Langfuse generation with metadata.

    Calls ``langfuse.update_current_generation()`` (v3 SDK).
    Use inside functions decorated with ``@trace(as_type="generation")``.

    Common kwargs:
        model: str — model name (e.g. "gemini-3-flash-preview")
        input: Any — input data
        output: Any — output data
        usage_details: dict — {"input": N, "output": M}
        cost_details: dict — {"input": 0.001, "output": 0.002}
        metadata: dict — arbitrary metadata

    No-op when tracing is disabled.
    """
    if _ENABLED and _get_client is not None:
        try:
            _get_client().update_current_generation(**kwargs)
        except Exception:
            logger.debug("Failed to update Langfuse generation", exc_info=True)


def update_current_trace(**kwargs: Any) -> None:
    """Update the current Langfuse trace with metadata.

    Common kwargs:
        user_id: str — user identifier
        session_id: str — session identifier
        metadata: dict — arbitrary metadata
        tags: list[str] — tags
        input: Any — trace input
        output: Any — trace output

    No-op when tracing is disabled.
    """
    if _ENABLED and _get_client is not None:
        try:
            _get_client().update_current_trace(**kwargs)
        except Exception:
            logger.debug("Failed to update Langfuse trace", exc_info=True)


# ── lifecycle ────────────────────────────────────────


def flush() -> None:
    """Flush pending Langfuse events. Call on shutdown."""
    if _ENABLED and _get_client is not None:
        try:
            _get_client().flush()
            logger.info("Langfuse events flushed")
        except Exception:
            logger.warning("Langfuse flush failed", exc_info=True)


def shutdown() -> None:
    """Flush and shutdown the Langfuse client. Call on app exit."""
    if _ENABLED and _get_client is not None:
        try:
            client = _get_client()
            client.flush()
            client.shutdown()
            logger.info("Langfuse client shutdown complete")
        except Exception:
            logger.warning("Langfuse shutdown failed", exc_info=True)
