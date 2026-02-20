"""
Patch generation with strategy pattern for each error type.
Routes failure context to the appropriate strategy to produce
minimal, valid patch ops per Blueprint §8 patch contract.

Allowed ops: actions.replace, actions.add, selectors.add,
selectors.replace, workflow.update_expect, policies.update
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from app.schemas.patch_schema import PatchOp, PlanPatchRequest, PlanPatchResponse


class PatchStrategy(ABC):
    """Base class for error-type-specific patch strategies."""

    @abstractmethod
    def generate(self, request: PlanPatchRequest) -> list[PatchOp]:
        ...

    @abstractmethod
    def explain(self, request: PlanPatchRequest) -> str:
        ...


class TargetNotFoundStrategy(PatchStrategy):
    """Generate actions.replace with alternative selector based on DOM snippet."""

    def generate(self, request: PlanPatchRequest) -> list[PatchOp]:
        alternative = self._find_alternative_selector(
            request.dom_snippet, request.failed_selector
        )
        if not alternative:
            return []

        target_key = request.failed_action.get("targetKey", request.step_id) if request.failed_action else request.step_id
        return [
            PatchOp(
                op="actions.replace",
                key=target_key,
                value={
                    "selector": alternative,
                    "description": f"Alternative selector for {request.step_id}",
                    "method": self._infer_method(request),
                    "arguments": [],
                },
            )
        ]

    def explain(self, request: PlanPatchRequest) -> str:
        return (
            f"Target not found at step '{request.step_id}'. "
            f"Original selector '{request.failed_selector or 'unknown'}' missing from DOM. "
            f"Replaced with alternative selector derived from DOM snippet."
        )

    def _find_alternative_selector(
        self, dom_snippet: str | None, failed_selector: str | None
    ) -> str | None:
        if not dom_snippet:
            return None

        # Try to find interactive elements: buttons, links, inputs
        patterns = [
            (r'<button[^>]*\bid=["\']([^"\']+)["\']', "button#{}"),
            (r'<a[^>]*\bid=["\']([^"\']+)["\']', "a#{}"),
            (r'<input[^>]*\bid=["\']([^"\']+)["\']', "input#{}"),
            (r'<button[^>]*\bdata-testid=["\']([^"\']+)["\']', '[data-testid="{}"]'),
            (r'<[^>]*\bdata-testid=["\']([^"\']+)["\']', '[data-testid="{}"]'),
            (r'<button[^>]*\brole=["\']([^"\']+)["\']', '[role="{}"]'),
            (r'<button[^>]*\bclass=["\']([^"\']+)["\']', "button.{}"),
            (r'<a[^>]*\bhref=["\']([^"\']+)["\']', 'a[href="{}"]'),
        ]

        for pattern, template in patterns:
            match = re.search(pattern, dom_snippet, re.IGNORECASE)
            if match:
                value = match.group(1)
                # For class-based selectors, use the first class only
                if "class" in pattern:
                    value = value.split()[0]
                candidate = template.format(value)
                # Don't return the same selector that failed
                if candidate != failed_selector:
                    return candidate

        return None

    def _infer_method(self, request: PlanPatchRequest) -> str:
        if request.failed_action and "method" in request.failed_action:
            return request.failed_action["method"]
        return "click"


class ExpectationFailedStrategy(PatchStrategy):
    """Generate workflow.update_expect based on actual page state."""

    def generate(self, request: PlanPatchRequest) -> list[PatchOp]:
        expectations = self._build_expectations(request)
        if not expectations:
            return []

        return [
            PatchOp(
                op="workflow.update_expect",
                step=request.step_id,
                value=expectations,
            )
        ]

    def explain(self, request: PlanPatchRequest) -> str:
        return (
            f"Expectation failed at step '{request.step_id}'. "
            f"Page state (URL: {request.url}, title: {request.title or 'unknown'}) "
            f"differs from expected. Updated expectations to match actual state."
        )

    def _build_expectations(self, request: PlanPatchRequest) -> list[dict]:
        expectations: list[dict] = []

        # Use current URL to build url_contains expectation
        if request.url:
            # Extract meaningful path segment from URL
            path = self._extract_path(request.url)
            if path and path != "/":
                expectations.append({"kind": "url_contains", "value": path})

        # Use title if available
        if request.title:
            expectations.append({"kind": "title_contains", "value": request.title})

        return expectations

    def _extract_path(self, url: str) -> str:
        """Extract the path portion from a URL."""
        # Remove protocol and domain
        match = re.match(r"https?://[^/]+(/.*)$", url)
        if match:
            return match.group(1)
        return "/"


class ExtractionEmptyStrategy(PatchStrategy):
    """Generate selectors.replace with broader scope."""

    def generate(self, request: PlanPatchRequest) -> list[PatchOp]:
        broader = self._broaden_selector(request.failed_selector, request.dom_snippet)
        if not broader:
            return []

        target_key = request.failed_action.get("targetKey", request.step_id) if request.failed_action else request.step_id
        return [
            PatchOp(
                op="selectors.replace",
                key=target_key,
                value={
                    "primary": broader,
                    "fallbacks": self._generate_fallbacks(broader, request.dom_snippet),
                    "strategy": "css",
                },
            )
        ]

    def explain(self, request: PlanPatchRequest) -> str:
        return (
            f"Extraction returned empty at step '{request.step_id}'. "
            f"Selector '{request.failed_selector or 'unknown'}' matched no elements. "
            f"Replaced with broader selector to capture content."
        )

    def _broaden_selector(
        self, failed_selector: str | None, dom_snippet: str | None
    ) -> str | None:
        if not failed_selector:
            # If no selector provided, try to find a container in DOM
            if dom_snippet:
                return self._find_container_selector(dom_snippet)
            return None

        # Strategy: remove specificity layers to broaden the selector
        # 1. If it has nth-child or nth-of-type, remove it
        broadened = re.sub(r":nth-(?:child|of-type)\(\d+\)", "", failed_selector)
        if broadened != failed_selector:
            return broadened

        # 2. If it's a deep descendant selector, remove the last segment
        parts = failed_selector.strip().split(" > ")
        if len(parts) > 1:
            return " > ".join(parts[:-1])

        parts = failed_selector.strip().split()
        if len(parts) > 1:
            return " ".join(parts[:-1])

        # 3. If it has an ID or class, try the tag name alone
        tag_match = re.match(r"^(\w+)", failed_selector)
        if tag_match and tag_match.group(1) != failed_selector:
            return tag_match.group(1)

        return None

    def _find_container_selector(self, dom_snippet: str) -> str | None:
        """Find a container element from the DOM snippet."""
        patterns = [
            r'<(div|section|main|article|table|ul|ol)[^>]*\bid=["\']([^"\']+)["\']',
            r'<(div|section|main|article|table|ul|ol)[^>]*\bclass=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, dom_snippet, re.IGNORECASE)
            if match:
                tag = match.group(1)
                attr_val = match.group(2)
                if "id=" in pattern:
                    return f"{tag}#{attr_val}"
                else:
                    first_class = attr_val.split()[0]
                    return f"{tag}.{first_class}"
        return None

    def _generate_fallbacks(self, primary: str, dom_snippet: str | None) -> list[str]:
        """Generate fallback selectors based on the primary."""
        fallbacks: list[str] = []

        # Add a tag-only fallback if primary has class/id
        tag_match = re.match(r"^(\w+)", primary)
        if tag_match:
            tag = tag_match.group(1)
            if tag != primary:
                fallbacks.append(tag)

        return fallbacks


class NotActionableStrategy(PatchStrategy):
    """Generate actions.replace with alternative interaction method."""

    # Fallback method chains: if one method fails, try the next
    METHOD_ALTERNATIVES: dict[str, list[str]] = {
        "click": ["focus", "press"],
        "fill": ["type", "press"],
        "type": ["fill", "press"],
        "press": ["click", "fill"],
        "focus": ["click"],
    }

    def generate(self, request: PlanPatchRequest) -> list[PatchOp]:
        failed_method = self._get_failed_method(request)
        alternatives = self.METHOD_ALTERNATIVES.get(failed_method, ["click"])
        new_method = alternatives[0]

        target_key = request.failed_action.get("targetKey", request.step_id) if request.failed_action else request.step_id
        selector = self._get_selector(request)

        return [
            PatchOp(
                op="actions.replace",
                key=target_key,
                value={
                    "selector": selector,
                    "description": f"Alternative interaction for {request.step_id} using {new_method}",
                    "method": new_method,
                    "arguments": self._get_arguments(request, new_method),
                },
            )
        ]

    def explain(self, request: PlanPatchRequest) -> str:
        failed_method = self._get_failed_method(request)
        return (
            f"Element not actionable at step '{request.step_id}'. "
            f"Method '{failed_method}' failed on selector '{self._get_selector(request)}'. "
            f"Replaced with alternative interaction method."
        )

    def _get_failed_method(self, request: PlanPatchRequest) -> str:
        if request.failed_action and "method" in request.failed_action:
            return request.failed_action["method"]
        return "click"

    def _get_selector(self, request: PlanPatchRequest) -> str:
        if request.failed_selector:
            return request.failed_selector
        if request.failed_action and "selector" in request.failed_action:
            return request.failed_action["selector"]
        return f"[data-step='{request.step_id}']"

    def _get_arguments(self, request: PlanPatchRequest, new_method: str) -> list[str]:
        """Carry over arguments when switching to a compatible method."""
        if request.failed_action and request.failed_action.get("arguments"):
            original_args = request.failed_action["arguments"]
            # fill/type are compatible - carry over text argument
            if new_method in ("fill", "type") and original_args:
                return original_args
            # press needs a key name
            if new_method == "press":
                return ["Enter"]
        if new_method == "press":
            return ["Enter"]
        return []


class PatchGenerator:
    """Route failure context to the appropriate strategy and produce a patch."""

    def __init__(self) -> None:
        self.strategies: dict[str, PatchStrategy] = {
            "TargetNotFound": TargetNotFoundStrategy(),
            "ExpectationFailed": ExpectationFailedStrategy(),
            "ExtractionEmpty": ExtractionEmptyStrategy(),
            "NotActionable": NotActionableStrategy(),
        }

    def generate_patch(self, request: PlanPatchRequest) -> PlanPatchResponse:
        strategy = self.strategies.get(request.error_type)
        if not strategy:
            return PlanPatchResponse(
                requestId=request.request_id,
                patch=[],
                reason=f"No strategy for error type '{request.error_type}'",
            )

        ops = strategy.generate(request)
        reason = strategy.explain(request)

        # If strategy could not produce ops, note it in the reason
        if not ops:
            reason += " However, insufficient context to generate a concrete patch."

        return PlanPatchResponse(
            requestId=request.request_id,
            patch=ops,
            reason=reason,
        )
