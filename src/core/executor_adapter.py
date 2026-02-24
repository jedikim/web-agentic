"""Executor adapter — IExecutor re-export + MockExecutor for testing.

Provides a MockExecutor that records all calls for assertion in tests,
and a factory function for convenient mock creation with overrides.
"""
from __future__ import annotations

from typing import Any

from src.core.types import ClickOptions, IExecutor, WaitCondition

# Re-export IExecutor for convenience
__all__ = ["IExecutor", "MockExecutor", "create_mock_executor"]


class MockExecutor:
    """Mock implementation of IExecutor that records all calls.

    Attributes:
        calls: List of (method_name, args, kwargs) tuples for every call.
    """

    def __init__(self, **overrides: Any) -> None:
        """Initialize MockExecutor with optional return value overrides.

        Args:
            overrides: Keyword arguments mapping method names to return values.
                       e.g. ``MockExecutor(screenshot=b"custom-png")``.
        """
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._overrides = overrides

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        """Record a method call and return the override or default value."""
        self.calls.append((name, args, kwargs))
        return self._overrides.get(name)

    async def goto(self, url: str) -> None:
        """Record goto call."""
        self._record("goto", (url,), {})

    async def click(self, selector: str, options: ClickOptions | None = None) -> None:
        """Record click call."""
        self._record("click", (selector,), {"options": options})

    async def type_text(self, selector: str, text: str) -> None:
        """Record type_text call."""
        self._record("type_text", (selector, text), {})

    async def press_key(self, key: str) -> None:
        """Record press_key call."""
        self._record("press_key", (key,), {})

    async def scroll(self, direction: str = "down", amount: int = 300) -> None:
        """Record scroll call."""
        self._record("scroll", (direction, amount), {})

    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Record screenshot call and return bytes."""
        result = self._record("screenshot", (), {"region": region})
        if result is not None:
            return result  # type: ignore[return-value]
        return b"mock-png"

    async def wait_for(self, condition: WaitCondition) -> None:
        """Record wait_for call."""
        self._record("wait_for", (condition,), {})

    async def get_page(self) -> object:
        """Record get_page call and return a placeholder."""
        result = self._record("get_page", (), {})
        return result

    async def get_page_state(self) -> dict[str, Any]:
        """Record get_page_state call and return mock state."""
        result = self._record("get_page_state", (), {})
        if result is not None:
            return result  # type: ignore[return-value]
        return {"url": "https://mock.example.com", "title": "Mock Page"}

    async def evaluate(self, expression: str) -> object:
        """Record evaluate call and return override or None."""
        result = self._record("evaluate", (expression,), {})
        return result

    async def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        """Record wait_for_selector call."""
        self._record("wait_for_selector", (selector,), {"timeout": timeout})


def create_mock_executor(**overrides: Any) -> MockExecutor:
    """Factory function to create a MockExecutor with optional overrides.

    Args:
        overrides: Keyword arguments mapping method names to return values.

    Returns:
        A configured MockExecutor instance.

    Example:
        >>> mock = create_mock_executor(screenshot=b"custom-data")
        >>> data = await mock.screenshot()
        >>> assert data == b"custom-data"
    """
    return MockExecutor(**overrides)
