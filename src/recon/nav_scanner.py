"""Navigation Scanner — Stage 3 of site reconnaissance.

Crawls the site via Playwright to discover URL patterns,
category trees, and page types. No LLM calls.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class PageLike(Protocol):
    """Minimal page interface for navigation scanning."""

    async def query_selector(self, selector: str) -> Any: ...
    async def goto(
        self, url: str, *, wait_until: str = "load", timeout: int = 30000
    ) -> None: ...


class BrowserLike(Protocol):
    """Minimal browser interface for navigation scanning."""

    page: PageLike

    async def evaluate(self, expression: str) -> Any: ...
    async def goto(
        self, url: str, *, wait_until: str = "load", timeout: int = 30000
    ) -> None: ...
    async def wait(self, ms: int) -> None: ...


class NavScanner:
    """Explore site navigation, categories, and URL patterns.

    Stage 3 of 3-stage recon. No LLM calls. Cost: $0, ~5s.
    """

    MAX_PAGES = 5
    MAX_MENU_DEPTH = 3

    async def scan(
        self,
        browser: BrowserLike,
        dom_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Run navigation scan.

        Args:
            browser: Browser for page navigation.
            dom_result: Results from DOM scanner.

        Returns:
            Dict with category_tree, page_samples, url_patterns.
        """
        category_tree: list[dict[str, Any]] = []
        page_samples: list[dict[str, Any]] = []
        url_patterns: set[str] = set()

        menu_items = dom_result.get("menu_items", [])
        for item in menu_items[:10]:
            if item.get("hasChildren"):
                children = await self._explore_submenu(browser, item)
                category_tree.append({
                    "name": item.get("text", ""),
                    "url": item.get("href", ""),
                    "children": children,
                })

        sample_urls = self._pick_sample_urls(category_tree, dom_result)
        for url in sample_urls[: self.MAX_PAGES]:
            page_info = await self._analyze_page(browser, url)
            if page_info:
                page_samples.append(page_info)
                url_patterns.add(self._extract_url_pattern(url))

        return {
            "category_tree": category_tree,
            "page_samples": page_samples,
            "url_patterns": list(url_patterns),
        }

    async def _explore_submenu(
        self, browser: BrowserLike, item: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Hover/click to explore submenu."""
        try:
            href = item.get("href", "")
            if not href:
                return []
            el = await browser.page.query_selector(f'a[href="{href}"]')
            if el:
                await el.hover()
                await browser.wait(500)
                children = await browser.evaluate(
                    """(() => {
                    const subs = document.querySelectorAll(
                        '.sub-menu:not([style*="none"]) a, ' +
                        '.dropdown-menu:not([style*="none"]) a, ' +
                        '[class*="depth2"]:not([style*="none"]) a'
                    );
                    return [...subs].slice(0, 20).map(a => ({
                        text: a.textContent.trim().slice(0, 50),
                        href: a.href,
                    }));
                })()"""
                )
                return children or []
        except Exception as e:
            logger.debug("Submenu exploration failed: %s", e)
        return []

    async def _analyze_page(
        self, browser: BrowserLike, url: str
    ) -> dict[str, Any] | None:
        """Analyze an individual page's content pattern."""
        try:
            await browser.goto(
                url, wait_until="domcontentloaded", timeout=10000
            )
            await browser.wait(1000)
            return await browser.evaluate(
                """(() => {
                const hasList = !!document.querySelector(
                    '[class*="product"], [class*="goods"], [class*="item-list"]'
                );
                const hasArticle = !!document.querySelector('article, .article, .post-content');
                const hasForm = document.querySelectorAll('form').length > 0;
                let pageType = 'other';
                if (hasList) pageType = 'product_list';
                else if (hasArticle) pageType = 'article';
                else if (hasForm) pageType = 'form';
                return {
                    url: location.href,
                    page_type: pageType,
                    title: document.title,
                    interactive_count: document.querySelectorAll(
                        'a, button, input, select, textarea'
                    ).length,
                    has_scroll_content: document.body.scrollHeight > window.innerHeight * 1.5,
                    images_count: document.images.length,
                };
            })()"""
            )
        except Exception as e:
            logger.warning("Page analysis failed for %s: %s", url, e)
            return None

    @staticmethod
    def _pick_sample_urls(
        category_tree: list[dict[str, Any]],
        dom_result: dict[str, Any],
    ) -> list[str]:
        """Pick diverse sample URLs to visit."""
        urls: list[str] = []
        # From category tree
        for cat in category_tree[:3]:
            if cat.get("url"):
                urls.append(cat["url"])
            for child in cat.get("children", [])[:2]:
                if child.get("href"):
                    urls.append(child["href"])
        return urls[:5]

    @staticmethod
    def _extract_url_pattern(url: str) -> str:
        """Extract URL pattern from a concrete URL.

        /search?query=shoes → /search?query=*
        /catalog/electronics → /catalog/*
        """
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path:
            return "/"

        # Replace last path segment with *
        segments = path.split("/")
        if len(segments) > 2:
            segments[-1] = "*"
        pattern = "/".join(segments)

        # Replace query values with *
        if parsed.query:
            params = re.sub(r"=[^&]*", "=*", parsed.query)
            pattern += "?" + params

        return pattern
