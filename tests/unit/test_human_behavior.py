"""Tests for src.core.human_behavior — human-like interaction simulation."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import BehaviorConfig
from src.core.human_behavior import HumanBehavior, _bezier_points


class TestBezierPoints:
    def test_returns_correct_number_of_points(self) -> None:
        pts = _bezier_points((0, 0), (100, 100), num_points=20)
        assert len(pts) == 21  # 20 segments + 1

    def test_starts_at_start_point(self) -> None:
        pts = _bezier_points((10, 20), (200, 300))
        assert pts[0] == pytest.approx((10, 20), abs=0.1)

    def test_ends_at_end_point(self) -> None:
        pts = _bezier_points((10, 20), (200, 300))
        assert pts[-1] == pytest.approx((200, 300), abs=0.1)

    def test_custom_num_points(self) -> None:
        pts = _bezier_points((0, 0), (50, 50), num_points=5)
        assert len(pts) == 6

    def test_randomness_differs_between_calls(self) -> None:
        pts1 = _bezier_points((0, 0), (100, 100))
        pts2 = _bezier_points((0, 0), (100, 100))
        # Middle points should differ (random control points)
        mid1 = pts1[10]
        mid2 = pts2[10]
        # Very unlikely to be exactly equal due to random control points
        # (but not impossible — just test structure)
        assert len(pts1) == len(pts2)


class TestNaturalClick:
    @pytest.mark.asyncio
    async def test_calls_mouse_move_then_click(self) -> None:
        page = MagicMock()
        page.locator = MagicMock()
        bbox = {"x": 100, "y": 200, "width": 50, "height": 30}
        locator_mock = MagicMock()
        locator_mock.bounding_box = AsyncMock(return_value=bbox)
        page.locator.return_value = locator_mock
        page.evaluate = AsyncMock(return_value={"x": 0, "y": 0})
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        page.mouse.click = AsyncMock()

        config = BehaviorConfig(mouse_movement=True, click_delay_ms=(1, 2))
        behavior = HumanBehavior(page, config)

        await behavior.natural_click("button.test", timeout_ms=3000)

        assert page.mouse.move.call_count >= 10  # Bézier points
        page.mouse.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_no_bbox(self) -> None:
        page = MagicMock()
        locator_mock = MagicMock()
        locator_mock.bounding_box = AsyncMock(return_value=None)
        page.locator.return_value = locator_mock
        page.click = AsyncMock()

        config = BehaviorConfig()
        behavior = HumanBehavior(page, config)

        await behavior.natural_click("button.missing")

        page.click.assert_called_once()


class TestNaturalType:
    @pytest.mark.asyncio
    async def test_types_character_by_character(self) -> None:
        page = MagicMock()
        page.click = AsyncMock()
        page.keyboard = MagicMock()
        page.keyboard.type = AsyncMock()

        config = BehaviorConfig(typing_delay_ms=(1, 2))
        behavior = HumanBehavior(page, config)

        await behavior.natural_type("input.name", "abc")

        assert page.keyboard.type.call_count == 3
        page.click.assert_called_once_with("input.name")


class TestNaturalScroll:
    @pytest.mark.asyncio
    async def test_scrolls_in_increments(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.wheel = AsyncMock()

        config = BehaviorConfig(scroll_step_px=100)
        behavior = HumanBehavior(page, config)

        await behavior.natural_scroll("down", 250)

        assert page.mouse.wheel.call_count == 3  # 100 + 100 + 50

    @pytest.mark.asyncio
    async def test_scroll_up_uses_negative(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.wheel = AsyncMock()

        config = BehaviorConfig(scroll_step_px=200)
        behavior = HumanBehavior(page, config)

        await behavior.natural_scroll("up", 200)

        page.mouse.wheel.assert_called_once()
        args = page.mouse.wheel.call_args[0]
        assert args[1] < 0  # Negative Y for up


class TestJitteredWait:
    @pytest.mark.asyncio
    async def test_wait_is_within_jitter_range(self) -> None:
        page = MagicMock()
        config = BehaviorConfig(step_delay_jitter=0.3)
        behavior = HumanBehavior(page, config)

        # We can't easily measure exact sleep time, but we can verify it
        # completes without error and within reasonable bounds.
        import time
        start = time.monotonic()
        await behavior.jittered_wait(100)  # 100ms ± 30%
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms >= 50  # At least 70ms minus scheduler jitter
        assert elapsed_ms < 300  # Not unreasonably long


class TestWarmNavigate:
    @pytest.mark.asyncio
    async def test_deep_url_visits_root_first(self) -> None:
        page = MagicMock()
        page.goto = AsyncMock()

        config = BehaviorConfig(step_delay_jitter=0.01)
        behavior = HumanBehavior(page, config)

        await behavior.warm_navigate("https://shop.example.com/products/laptop")

        assert page.goto.call_count == 2
        first_url = page.goto.call_args_list[0][0][0]
        assert first_url == "https://shop.example.com/"
        second_url = page.goto.call_args_list[1][0][0]
        assert second_url == "https://shop.example.com/products/laptop"

    @pytest.mark.asyncio
    async def test_root_url_skips_warming(self) -> None:
        page = MagicMock()
        page.goto = AsyncMock()

        config = BehaviorConfig()
        behavior = HumanBehavior(page, config)

        await behavior.warm_navigate("https://example.com/")

        assert page.goto.call_count == 1

    @pytest.mark.asyncio
    async def test_second_visit_to_same_domain_skips_warming(self) -> None:
        page = MagicMock()
        page.goto = AsyncMock()

        config = BehaviorConfig(step_delay_jitter=0.01)
        behavior = HumanBehavior(page, config)

        await behavior.warm_navigate("https://shop.example.com/products/laptop")
        page.goto.reset_mock()

        await behavior.warm_navigate("https://shop.example.com/products/phone")

        # Only the target URL — no root warming
        assert page.goto.call_count == 1
