"""ResultVerifier — post-action result verification.

Verifies that an action produced the intended result.
Does NOT verify before execution — only after.

Verification priority:
1. URL assertion (deterministic, most reliable)
2. DOM assertion (element exists/absent after action)
3. Vision comparison (pHash fallback — last resort)

Returns: "ok" | "wrong" | "failed"
"""

from __future__ import annotations

import logging

from src.core.browser import Browser
from src.core.types import Action, CacheEntry, StepPlan

logger = logging.getLogger(__name__)


class ResultVerifier:
    """Verify action results post-execution.

    Usage:
        verifier = ResultVerifier()
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, cached, browser, pre_url,
        )
    """

    PHASH_THRESHOLD = 12

    async def verify_result(
        self,
        pre_screenshot: bytes,
        post_screenshot: bytes,
        action: Action | None,
        step_or_cache: CacheEntry | StepPlan,
        browser: Browser,
        pre_url: str,
    ) -> str:
        """Verify whether the action produced the intended result.

        Args:
            pre_screenshot: Screenshot bytes before action.
            post_screenshot: Screenshot bytes after action.
            action: The action that was executed.
            step_or_cache: StepPlan or CacheEntry with expected_result.
            browser: Browser for DOM queries.
            pre_url: URL before the action.

        Returns:
            "ok" — result matches intention, cache valid.
            "wrong" — something happened but not what was intended.
            "failed" — nothing happened, click was blocked.
        """
        expected = step_or_cache.expected_result

        logger.debug(
            "Verifying: expected=%s, pre_url=%s, post_url=%s",
            expected, pre_url, browser.url,
        )

        # ===== 1: URL-based verification (deterministic) =====
        url_changed = browser.url != pre_url

        if expected and "URL" in expected:
            url_hint = self._extract_url_hint(expected)
            if url_hint:
                if url_hint in browser.url:
                    logger.debug("URL hint matched: %s", url_hint)
                    return "ok"
                if url_changed:
                    # For StepPlan (not CacheEntry), URL hint is a prediction.
                    # Any URL change means the action worked — just navigated
                    # to a different page than predicted.
                    if isinstance(step_or_cache, StepPlan):
                        logger.debug(
                            "URL changed (hint %s not matched, but step "
                            "action caused navigation): %s",
                            url_hint, browser.url,
                        )
                        return "ok"
                    logger.debug(
                        "URL changed but hint not matched: %s not in %s",
                        url_hint, browser.url,
                    )
                    return "wrong"
                logger.debug("URL not changed, expected: %s", url_hint)
                return "failed"

        # ===== 2: DOM assertion (element exists) =====
        if expected and "DOM" in expected:
            dom_selector = self._extract_dom_hint(expected)
            if dom_selector:
                safe = dom_selector.replace("\\", "\\\\").replace("'", "\\'")
                try:
                    exists = await browser.evaluate(
                        f"!!document.querySelector('{safe}')"
                    )
                except Exception:
                    exists = False
                if exists:
                    logger.debug("DOM selector found: %s", dom_selector)
                    return "ok"
                if url_changed:
                    logger.debug(
                        "URL changed but DOM selector not found: %s",
                        dom_selector,
                    )
                    return "wrong"
                logger.debug("DOM selector not found: %s", dom_selector)
                return "failed"

        # URL changed without specific expectation → likely success
        if url_changed:
            logger.debug(
                "URL changed (no specific expectation): %s → %s",
                pre_url, browser.url,
            )
            return "ok"

        # ===== 2.5: Action-type-aware DOM verification =====
        dom_result = await self._verify_by_action_type(action, browser)
        if dom_result is not None:
            return dom_result

        # ===== 2.6: New tab detection (target="_blank" links) =====
        new_tab = await self._check_new_tab(browser)
        if new_tab:
            return "ok"

        # ===== 3: Vision comparison (pHash fallback) =====
        changed = self._screenshots_differ(pre_screenshot, post_screenshot)

        if not changed:
            logger.debug("Screenshots identical — action had no effect")
            return "failed"

        # If we have a reference screenshot hash, compare
        if isinstance(step_or_cache, CacheEntry) and step_or_cache.post_screenshot_phash:
            post_distance = self._phash_distance(
                post_screenshot, step_or_cache.post_screenshot_phash,
            )
            if post_distance > self.PHASH_THRESHOLD:
                logger.debug(
                    "pHash distance %d > threshold %d",
                    post_distance, self.PHASH_THRESHOLD,
                )
                return "wrong"

        logger.debug("Screenshots differ — action succeeded")
        return "ok"

    async def _check_new_tab(self, browser: Browser) -> bool:
        """Check if a new tab was opened (target='_blank' links)."""
        try:
            pages = browser.context.pages
            if len(pages) > 1:
                logger.debug(
                    "New tab detected (%d pages total)", len(pages),
                )
                return True
        except Exception:
            pass
        return False

    async def _verify_by_action_type(
        self, action: Action | None, browser: Browser,
    ) -> str | None:
        """Verify based on the action type using DOM inspection.

        Returns "ok"/"failed" if deterministic, None to fall through to pHash.
        """
        if not action or not action.selector:
            return None

        safe = action.selector.replace("\\", "\\\\").replace("'", "\\'")
        act = (action.action_type or "").lower()

        # Type/fill: check if the input's value matches what was typed
        if act in ("type", "fill") and action.value:
            try:
                current_value: str = await browser.evaluate(
                    f"(() => {{"
                    f"  const el = document.querySelector('{safe}');"
                    f"  return el ? el.value : null;"
                    f"}})()"
                )
                if current_value is not None and action.value in current_value:
                    logger.debug(
                        "Type verify OK: input value '%s' contains '%s'",
                        current_value[:50], action.value[:30],
                    )
                    return "ok"
            except Exception:
                pass
            return None

        # Click on checkbox/radio: check if element is now checked
        if act == "click":
            try:
                check_result = await browser.evaluate(
                    f"(() => {{"
                    f"  const el = document.querySelector('{safe}');"
                    f"  if (!el) return null;"
                    f"  const tag = el.tagName.toLowerCase();"
                    f"  const type = (el.type || '').toLowerCase();"
                    f"  if (tag === 'input' && (type === 'checkbox' || type === 'radio'))"
                    f"    return el.checked;"
                    f"  return null;"
                    f"}})()"
                )
                if check_result is True:
                    logger.debug("Checkbox/radio verify OK: element is checked")
                    return "ok"
                if check_result is False:
                    logger.debug("Checkbox/radio verify: element not checked")
                    return "failed"
            except Exception:
                pass

        return None

    def _screenshots_differ(
        self, pre: bytes, post: bytes,
    ) -> bool:
        """Check if screenshots are meaningfully different."""
        try:
            import io

            from imagehash import phash  # type: ignore[import-untyped]
            from PIL import Image

            pre_img = Image.open(io.BytesIO(pre))
            post_img = Image.open(io.BytesIO(post))
            pre_hash = phash(pre_img)
            post_hash = phash(post_img)
            return (pre_hash - post_hash) > 3
        except ImportError:
            # imagehash not installed — assume changed if bytes differ
            return pre != post

    def _phash_distance(self, screenshot: bytes, reference_hash: str) -> int:
        """Compute pHash distance between screenshot and reference."""
        try:
            import io

            from imagehash import hex_to_hash, phash  # type: ignore[import-untyped]
            from PIL import Image

            img = Image.open(io.BytesIO(screenshot))
            current = phash(img)
            ref = hex_to_hash(reference_hash)
            return current - ref
        except (ImportError, ValueError):
            return 0  # Can't compare — assume ok

    def _extract_url_hint(self, expected_result: str) -> str | None:
        """Extract URL hint from expected_result string.

        Example: 'URL 변경: /category/sports' → '/category/sports'
        """
        if "URL" in expected_result and ":" in expected_result:
            return expected_result.split(":", 1)[1].strip()
        return None

    def _extract_dom_hint(self, expected_result: str) -> str | None:
        """Extract DOM selector hint from expected_result string.

        Example: 'DOM 존재: .search-results' → '.search-results'
        """
        if "DOM" in expected_result and ":" in expected_result:
            return expected_result.split(":", 1)[1].strip()
        return None
