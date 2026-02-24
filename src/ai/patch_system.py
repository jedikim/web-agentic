"""Patch Applicator — applies LLM-produced PatchData to the system.

Implements the Patch-Only output principle (P3): the LLM never generates
free-form code, only structured patches that are validated and applied
through this controlled interface.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.types import PatchData

logger = logging.getLogger(__name__)

# ── Valid patch types and their required data keys ────

_PATCH_SCHEMAS: dict[str, set[str]] = {
    "selector_fix": {"new_selector"},
    "param_change": {"param_name", "new_value"},
    "rule_add": {"rule_id", "category", "intent_pattern", "selector"},
    "strategy_switch": {"new_strategy"},
}

VALID_PATCH_TYPES = frozenset(_PATCH_SCHEMAS.keys())


class PatchSystem:
    """Validates and applies structured patches from LLM output.

    Each patch type has a dedicated handler that modifies the context dict
    in a controlled, auditable way.
    """

    def validate_patch(self, patch: PatchData) -> bool:
        """Validate that a patch is well-formed and applicable.

        Args:
            patch: The patch to validate.

        Returns:
            True if the patch is valid.

        Checks:
        - patch_type is a recognised type.
        - Required data keys are present.
        - confidence is within [0.0, 1.0].
        - target is non-empty.
        """
        if patch.patch_type not in VALID_PATCH_TYPES:
            logger.warning("Invalid patch type: %r", patch.patch_type)
            return False

        if not patch.target:
            logger.warning("Patch target is empty")
            return False

        if not (0.0 <= patch.confidence <= 1.0):
            logger.warning("Patch confidence out of range: %s", patch.confidence)
            return False

        required_keys = _PATCH_SCHEMAS[patch.patch_type]
        missing = required_keys - set(patch.data.keys())
        if missing:
            logger.warning(
                "Patch %r missing required data keys: %s",
                patch.patch_type,
                missing,
            )
            return False

        return True

    def apply_patch(self, patch: PatchData, context: dict[str, Any]) -> dict[str, Any]:
        """Apply a validated patch to the given context.

        Args:
            patch: The patch to apply.
            context: Mutable context dict to be modified.

        Returns:
            The modified context dict.

        Raises:
            ValueError: If the patch is invalid.
        """
        if not self.validate_patch(patch):
            raise ValueError(
                f"Invalid patch: type={patch.patch_type!r}, "
                f"target={patch.target!r}, data={patch.data!r}"
            )

        handler = _PATCH_HANDLERS.get(patch.patch_type)
        if handler is None:
            raise ValueError(f"No handler for patch type: {patch.patch_type!r}")

        logger.info(
            "Applying patch type=%r target=%r confidence=%.2f",
            patch.patch_type,
            patch.target,
            patch.confidence,
        )
        return handler(patch, context)


# ── Patch handlers ───────────────────────────────────


def _apply_selector_fix(
    patch: PatchData, context: dict[str, Any]
) -> dict[str, Any]:
    """Replace a failed selector with a new one.

    Updates the ``selectors`` mapping in context, moving the old
    selector to ``replaced_selectors`` for audit trail.
    """
    old_selector = patch.target
    new_selector = patch.data["new_selector"]
    strategy = patch.data.get("strategy", "unknown")

    # Track replacement history
    replaced = context.setdefault("replaced_selectors", [])
    replaced.append(
        {
            "old": old_selector,
            "new": new_selector,
            "strategy": strategy,
            "confidence": patch.confidence,
        }
    )

    # Update active selectors
    selectors = context.setdefault("selectors", {})
    selectors[old_selector] = new_selector

    logger.debug(
        "Selector fix: %r -> %r (strategy=%s)", old_selector, new_selector, strategy
    )
    return context


def _apply_param_change(
    patch: PatchData, context: dict[str, Any]
) -> dict[str, Any]:
    """Change a step parameter (timeout, max_attempts, etc.)."""
    param_name = patch.data["param_name"]
    new_value = patch.data["new_value"]
    target = patch.target

    # Store parameter overrides
    overrides = context.setdefault("param_overrides", {})
    target_overrides = overrides.setdefault(target, {})
    target_overrides[param_name] = new_value

    logger.debug("Param change: %s.%s = %r", target, param_name, new_value)
    return context


def _apply_rule_add(
    patch: PatchData, context: dict[str, Any]
) -> dict[str, Any]:
    """Add a new rule to the rule engine via context."""
    rule_data = {
        "rule_id": patch.data["rule_id"],
        "category": patch.data["category"],
        "intent_pattern": patch.data["intent_pattern"],
        "selector": patch.data["selector"],
        "method": patch.data.get("method", "click"),
        "priority": patch.data.get("priority", 0),
        "confidence": patch.confidence,
    }

    pending_rules = context.setdefault("pending_rules", [])
    pending_rules.append(rule_data)

    logger.debug("Rule add: %s (category=%s)", rule_data["rule_id"], rule_data["category"])
    return context


def _apply_strategy_switch(
    patch: PatchData, context: dict[str, Any]
) -> dict[str, Any]:
    """Switch the recovery strategy for a target step/module."""
    new_strategy = patch.data["new_strategy"]
    target = patch.target

    # Store strategy overrides
    strategies = context.setdefault("strategy_overrides", {})
    strategies[target] = new_strategy

    logger.debug("Strategy switch: %s -> %r", target, new_strategy)
    return context


_PATCH_HANDLERS: dict[
    str,
    Any,
] = {
    "selector_fix": _apply_selector_fix,
    "param_change": _apply_param_change,
    "rule_add": _apply_rule_add,
    "strategy_switch": _apply_strategy_switch,
}
