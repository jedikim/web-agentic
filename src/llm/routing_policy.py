"""Task-specific model routing policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.llm.router import LLMRouter


@dataclass
class RoutingRule:
    """Routing rule for a task type."""

    alias: str  # primary model alias
    fallbacks: list[str]
    max_tokens: int
    temperature: float


# Default routing policies per task type
ROUTING_POLICY: dict[str, RoutingRule] = {
    "recon_synthesize": RoutingRule("fast", ["strong"], 4000, 0.1),
    "codegen": RoutingRule("codegen", ["strong", "fast"], 8000, 0.1),
    "codegen_complex": RoutingRule("codegen", ["strong"], 12000, 0.05),
    "selector_fix": RoutingRule("fast", ["strong"], 2000, 0.0),
    "failure_analysis": RoutingRule("strong", ["fast"], 1500, 0.0),
    "vision_analysis": RoutingRule("vision", ["fast"], 3000, 0.1),
}


class ModelRouter:
    """Task-type aware routing with context window fallback."""

    def __init__(self, llm_router: LLMRouter) -> None:
        self._router = llm_router

    async def call(
        self,
        task_type: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Route a call based on task type.

        Args:
            task_type: One of the ROUTING_POLICY keys.
            messages: Chat messages.
            **kwargs: Extra parameters.

        Returns:
            LLM response text.
        """
        rule = ROUTING_POLICY.get(
            task_type,
            RoutingRule("fast", ["strong"], 2000, 0.2),
        )
        try:
            return await self._router.complete(
                rule.alias,
                messages,
                max_tokens=rule.max_tokens,
                temperature=rule.temperature,
                **kwargs,
            )
        except Exception:
            # Try fallbacks
            for fb_alias in rule.fallbacks:
                try:
                    return await self._router.complete(
                        fb_alias,
                        messages,
                        max_tokens=rule.max_tokens,
                        temperature=rule.temperature,
                        **kwargs,
                    )
                except Exception:
                    continue
            raise
