"""Tests for ResultVerifier — post-action verification."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.browser import Browser
from src.core.result_verifier import ResultVerifier
from src.core.types import Action, CacheEntry, StepPlan


@pytest.fixture
def verifier() -> ResultVerifier:
    return ResultVerifier()


@pytest.fixture
def mock_browser() -> Browser:
    page = AsyncMock()
    page.url = "https://example.com/after"
    page.evaluate = AsyncMock(return_value=True)
    page.context = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=AsyncMock())
    return Browser(page)


@pytest.fixture
def action() -> Action:
    return Action(selector="#btn", action_type="click")


@pytest.fixture
def pre_screenshot() -> bytes:
    return b"pre-screenshot-bytes"


@pytest.fixture
def post_screenshot() -> bytes:
    return b"post-screenshot-bytes"


class TestURLVerification:
    async def test_url_match_returns_ok(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com/category/sports"
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="스포츠 메뉴",
            expected_result="URL 변경: /category/sports",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "ok"

    async def test_url_wrong_returns_ok_for_step_plan(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        """StepPlan URL hint is a prediction — any URL change is ok."""
        mock_browser._page.url = "https://example.com/login"
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="스포츠 메뉴",
            expected_result="URL 변경: /category/sports",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "ok"

    async def test_url_wrong_returns_wrong_for_cache(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        """CacheEntry URL hint is exact — mismatch returns wrong."""
        mock_browser._page.url = "https://example.com/login"
        cached = CacheEntry(
            domain="example.com",
            url_pattern="https://example.com",
            task_type="스포츠 메뉴 클릭",
            selector="#btn",
            action_type="click",
            expected_result="URL 변경: /category/sports",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, cached,
            mock_browser, "https://example.com",
        )
        assert result == "wrong"

    async def test_url_not_changed_returns_failed(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com"
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="스포츠 메뉴",
            expected_result="URL 변경: /category/sports",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "failed"


class TestDOMVerification:
    async def test_dom_exists_returns_ok(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com"  # Same URL
        mock_browser._page.evaluate = AsyncMock(return_value=True)
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="드롭다운 열기",
            expected_result="DOM 존재: .dropdown-menu",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "ok"

    async def test_dom_not_exists_returns_failed(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com"
        mock_browser._page.evaluate = AsyncMock(return_value=False)
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="드롭다운 열기",
            expected_result="DOM 존재: .dropdown-menu",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "failed"

    async def test_dom_not_exists_url_changed_returns_wrong(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com/other"
        mock_browser._page.evaluate = AsyncMock(return_value=False)
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="드롭다운 열기",
            expected_result="DOM 존재: .dropdown-menu",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "wrong"


class TestURLChangedFallback:
    async def test_url_changed_no_expectation_returns_ok(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com/new-page"
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="어딘가 클릭",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "ok"


class TestVisionFallback:
    @staticmethod
    def _make_png(pattern: str = "solid") -> bytes:
        """Create a valid PNG image with distinct patterns."""
        import io

        from PIL import Image, ImageDraw
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        if pattern == "solid":
            draw.rectangle([0, 0, 200, 200], fill=(128, 128, 128))
        elif pattern == "complex":
            # Draw many rectangles to create a very different hash
            for i in range(20):
                x = i * 10
                draw.rectangle([x, 0, x + 8, 200], fill=(i * 12, 0, 255 - i * 12))
            draw.ellipse([50, 50, 150, 150], fill=(255, 0, 0))
            draw.text((10, 10), "CHANGED", fill=(0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def test_same_screenshots_returns_failed(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action,
    ) -> None:
        mock_browser._page.url = "https://example.com"
        same_bytes = self._make_png("solid")
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="뭔가 클릭",
        )
        result = await verifier.verify_result(
            same_bytes, same_bytes, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "failed"

    async def test_different_screenshots_returns_ok(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action,
    ) -> None:
        mock_browser._page.url = "https://example.com"
        pre = self._make_png("solid")    # Uniform gray
        post = self._make_png("complex")  # Complex pattern (very different pHash)
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="뭔가 클릭",
        )
        result = await verifier.verify_result(
            pre, post, action, step,
            mock_browser, "https://example.com",
        )
        assert result == "ok"


class TestExtractHints:
    def test_extract_url_hint(self, verifier: ResultVerifier) -> None:
        hint = verifier._extract_url_hint("URL 변경: /category/sports")
        assert hint == "/category/sports"

    def test_extract_url_hint_none(self, verifier: ResultVerifier) -> None:
        assert verifier._extract_url_hint("no url here") is None

    def test_extract_dom_hint(self, verifier: ResultVerifier) -> None:
        hint = verifier._extract_dom_hint("DOM 존재: .search-results")
        assert hint == ".search-results"

    def test_extract_dom_hint_complex(self, verifier: ResultVerifier) -> None:
        hint = verifier._extract_dom_hint("DOM 존재: #dropdown[aria-expanded=true]")
        assert hint == "#dropdown[aria-expanded=true]"

    def test_extract_dom_hint_none(self, verifier: ResultVerifier) -> None:
        assert verifier._extract_dom_hint("no dom here") is None


class TestWithCacheEntry:
    async def test_cache_entry_url_check(
        self, verifier: ResultVerifier, mock_browser: Browser,
        action: Action, pre_screenshot: bytes, post_screenshot: bytes,
    ) -> None:
        mock_browser._page.url = "https://example.com/product/123"
        cache = CacheEntry(
            domain="example.com",
            url_pattern="https://example.com/*",
            task_type="상품 클릭",
            selector="#product-link",
            action_type="click",
            expected_result="URL 변경: /product/",
        )
        result = await verifier.verify_result(
            pre_screenshot, post_screenshot, action, cache,
            mock_browser, "https://example.com",
        )
        assert result == "ok"
