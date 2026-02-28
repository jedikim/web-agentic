"""Unit tests for observability tracing — no-op decorator behavior.

Since LANGFUSE_ENABLED defaults to false, all decorators should be
transparent no-ops that don't affect function behavior.
"""
from __future__ import annotations

from src.observability.tracing import (
    flush,
    is_enabled,
    shutdown,
    trace,
    update_current_observation,
    update_current_trace,
)


class TestTracingDisabled:
    """Tests for tracing when LANGFUSE_ENABLED=false (default)."""

    def test_is_not_enabled(self) -> None:
        assert is_enabled() is False

    def test_trace_noop_sync(self) -> None:
        """@trace should not alter sync function behavior."""

        @trace(name="test-fn")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    async def test_trace_noop_async(self) -> None:
        """@trace should not alter async function behavior."""

        @trace(name="test-async")
        async def fetch(url: str) -> str:
            return f"response from {url}"

        result = await fetch("https://example.com")
        assert result == "response from https://example.com"

    def test_trace_with_generation_type(self) -> None:
        """@trace with as_type='generation' should still be no-op."""

        @trace(name="llm-call", as_type="generation")
        def generate(prompt: str) -> str:
            return f"answer to: {prompt}"

        assert generate("hello") == "answer to: hello"

    def test_update_observation_noop(self) -> None:
        """update_current_observation should not raise when disabled."""
        update_current_observation(
            model="gemini-3-flash",
            usage_details={"input": 100, "output": 50},
        )

    def test_update_trace_noop(self) -> None:
        """update_current_trace should not raise when disabled."""
        update_current_trace(
            name="test-trace",
            metadata={"key": "value"},
        )

    def test_flush_noop(self) -> None:
        """flush should not raise when disabled."""
        flush()

    def test_shutdown_noop(self) -> None:
        """shutdown should not raise when disabled."""
        shutdown()

    def test_decorated_preserves_name(self) -> None:
        """Decorated function should preserve __name__."""

        @trace(name="my-fn")
        def my_function() -> int:
            return 42

        assert my_function.__name__ == "my_function"

    async def test_decorated_preserves_async_name(self) -> None:
        """Decorated async function should preserve __name__."""

        @trace(name="my-async-fn")
        async def my_async_function() -> int:
            return 42

        assert my_async_function.__name__ == "my_async_function"
        assert await my_async_function() == 42

    def test_trace_no_kwargs(self) -> None:
        """@trace() with no kwargs should work."""

        @trace()
        def simple() -> str:
            return "ok"

        assert simple() == "ok"
