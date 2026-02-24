"""Navigation intelligence — rate limiting, robots.txt, homepage warming.

Provides a ``NavigationGuard`` that is consulted before every ``goto()`` call.
Uses Python stdlib ``urllib.robotparser`` — no external dependencies.

Key behaviours:
- **Rate limiting**: minimum interval between navigations to the same domain.
- **robots.txt**: fetches and caches rules per domain, blocks disallowed paths.
- **Homepage warming**: visits root domain before deep URLs on first access.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from src.core.config import NavigationConfig

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────


class NavigationBlockedError(Exception):
    """Raised when a URL is blocked by robots.txt."""

    def __init__(self, url: str, reason: str = "robots.txt") -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Navigation blocked ({reason}): {url}")


# ── NavigationGuard ──────────────────────────────────


class NavigationGuard:
    """Pre-navigation checks: rate-limit → robots.txt → homepage warming.

    Args:
        config: Navigation configuration.
        user_agent: User-agent string for robots.txt checking.
    """

    def __init__(
        self,
        config: NavigationConfig,
        user_agent: str = "*",
    ) -> None:
        self._config = config
        self._user_agent = user_agent
        self._last_access: dict[str, float] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._visited_domains: set[str] = set()

    async def pre_navigate(self, url: str, page: Page) -> None:
        """Run all pre-navigation checks.

        Calling order:
        1. Rate limiting (same-domain throttle).
        2. robots.txt compliance check.
        3. Homepage warming (root visit for deep URLs).

        Args:
            url: The target URL.
            page: The Playwright Page (used for homepage warming goto).

        Raises:
            NavigationBlockedError: If robots.txt disallows the URL.
        """
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        # 1. Rate limiting
        await self._rate_limit(domain)

        # 2. robots.txt check
        if self._config.respect_robots_txt:
            allowed = await self._check_robots(url, domain)
            if not allowed:
                raise NavigationBlockedError(url)

        # 3. Homepage warming
        if self._config.homepage_first:
            await self._warm_homepage(url, parsed, domain, page)

        # Record access time
        self._last_access[domain] = time.monotonic()

    async def _rate_limit(self, domain: str) -> None:
        """Enforce minimum interval between navigations to the same domain."""
        last = self._last_access.get(domain)
        if last is not None:
            elapsed_ms = (time.monotonic() - last) * 1000
            remaining_ms = self._config.rate_limit_ms - elapsed_ms
            if remaining_ms > 0:
                logger.debug(
                    "Rate limiting %s: waiting %.0fms", domain, remaining_ms,
                )
                await asyncio.sleep(remaining_ms / 1000)

    async def _check_robots(self, url: str, domain: str) -> bool:
        """Check if the URL is allowed by robots.txt.

        Fetches and caches robots.txt per domain. Returns True if the
        URL is allowed or if robots.txt is unavailable.
        """
        if domain not in self._robots_cache:
            self._robots_cache[domain] = await self._fetch_robots(domain, url)

        rp = self._robots_cache[domain]
        if rp is None:
            return True  # No robots.txt found → allow

        allowed = rp.can_fetch(self._user_agent, url)
        if not allowed:
            logger.warning("robots.txt blocks: %s", url)
        return allowed

    async def _fetch_robots(
        self, domain: str, sample_url: str,
    ) -> RobotFileParser | None:
        """Fetch and parse robots.txt for a domain.

        Returns None if robots.txt is unreachable.
        """
        parsed = urlparse(sample_url)
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"

        rp = RobotFileParser()
        rp.set_url(robots_url)

        try:
            # Run blocking read in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, rp.read)
            logger.info("Loaded robots.txt for %s", domain)
            return rp
        except Exception as exc:
            logger.debug("Could not fetch robots.txt for %s: %s", domain, exc)
            return None

    async def _warm_homepage(
        self,
        url: str,
        parsed: Any,
        domain: str,
        page: Page,
    ) -> None:
        """Visit root domain before deep URLs on first access."""
        path_parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
        if len(path_parts) <= 1:
            return  # Not a deep URL

        if domain in self._visited_domains:
            return  # Already warmed

        root_url = f"{parsed.scheme}://{domain}/"
        logger.info("Homepage warming: visiting %s before %s", root_url, url)
        try:
            await page.goto(root_url)
            # Small wait to simulate reading
            await asyncio.sleep(1.0 + 1.0 * (id(page) % 10) / 10)
        except Exception as exc:
            logger.warning("Homepage warming failed: %s", exc)

        self._visited_domains.add(domain)
