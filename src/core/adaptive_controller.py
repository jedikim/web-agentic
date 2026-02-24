"""Adaptive controller — detects repeated intents and provides cached steps.

Wraps :class:`ReplayStore` to reduce LLM cost for repeated site+intent
combinations by returning previously successful execution plans.
"""
from __future__ import annotations

from src.learning.replay_store import ReplayStore


class AdaptiveController:
    """Detects repeated intents and provides cached steps to reduce LLM cost."""

    def __init__(
        self,
        replay_store: ReplayStore,
        min_successes: int = 3,
    ) -> None:
        self._store = replay_store
        self._min_successes = min_successes

    async def should_use_cache(self, site: str, intent: str) -> bool:
        """Check if cached steps are available for this site+intent.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.

        Returns:
            ``True`` if enough successful traces exist.
        """
        cached = await self._store.find_similar(
            site, intent, self._min_successes,
        )
        return cached is not None

    async def get_cached_steps(self, site: str, intent: str) -> list[object] | None:
        """Return cached steps if available.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.

        Returns:
            Deserialized steps list, or ``None`` if not enough history.
        """
        return await self._store.find_similar(
            site, intent, self._min_successes,
        )

    async def record_execution(
        self,
        site: str,
        intent: str,
        steps: list[object],
        cost: float,
        success: bool,
    ) -> None:
        """Record execution result to replay store.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.
            steps: Executed step data.
            cost: Total cost in USD.
            success: Whether the execution succeeded.
        """
        await self._store.record(site, intent, steps, cost, success)
