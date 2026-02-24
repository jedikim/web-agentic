"""Tests for src.core.stealth — browser anti-detection patches."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import StealthConfig
from src.core.stealth import (
    _USER_AGENTS,
    _get_patches,
    apply_stealth,
    create_stealth_context,
    get_patch_count,
)


class TestGetPatches:
    def test_minimal_has_one_patch(self) -> None:
        patches = _get_patches("minimal")
        assert len(patches) == 1  # webdriver only

    def test_standard_has_five_patches(self) -> None:
        patches = _get_patches("standard")
        assert len(patches) == 5  # webdriver + runtime + plugins + mimetypes + permissions

    def test_aggressive_has_seven_patches(self) -> None:
        patches = _get_patches("aggressive")
        assert len(patches) == 7  # standard 5 + webgl + canvas

    def test_get_patch_count_matches(self) -> None:
        for level in ("minimal", "standard", "aggressive"):
            assert get_patch_count(level) == len(_get_patches(level))


class TestApplyStealth:
    @pytest.mark.asyncio
    async def test_adds_init_scripts_for_standard(self) -> None:
        context = MagicMock()
        context.add_init_script = AsyncMock()
        config = StealthConfig(level="standard")

        await apply_stealth(context, config)

        assert context.add_init_script.call_count == 5

    @pytest.mark.asyncio
    async def test_adds_init_scripts_for_aggressive(self) -> None:
        context = MagicMock()
        context.add_init_script = AsyncMock()
        config = StealthConfig(level="aggressive")

        await apply_stealth(context, config)

        assert context.add_init_script.call_count == 7

    @pytest.mark.asyncio
    async def test_disabled_skips_all_patches(self) -> None:
        context = MagicMock()
        context.add_init_script = AsyncMock()
        config = StealthConfig(enabled=False)

        await apply_stealth(context, config)

        context.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_minimal_adds_one_patch(self) -> None:
        context = MagicMock()
        context.add_init_script = AsyncMock()
        config = StealthConfig(level="minimal")

        await apply_stealth(context, config)

        assert context.add_init_script.call_count == 1

    @pytest.mark.asyncio
    async def test_webdriver_patch_always_present(self) -> None:
        context = MagicMock()
        context.add_init_script = AsyncMock()
        config = StealthConfig(level="minimal")

        await apply_stealth(context, config)

        script = context.add_init_script.call_args_list[0][0][0]
        assert "navigator" in script
        assert "webdriver" in script


class TestCreateStealthContext:
    @pytest.mark.asyncio
    async def test_creates_context_with_viewport_and_ua(self) -> None:
        browser = MagicMock()
        context_mock = MagicMock()
        context_mock.add_init_script = AsyncMock()
        browser.new_context = AsyncMock(return_value=context_mock)

        config = StealthConfig(
            randomize_viewport=False,
            user_agent="TestUA/1.0",
        )

        ctx = await create_stealth_context(browser, config)

        browser.new_context.assert_called_once()
        call_kwargs = browser.new_context.call_args.kwargs
        assert call_kwargs["user_agent"] == "TestUA/1.0"
        assert call_kwargs["viewport"]["width"] == 1920
        assert call_kwargs["viewport"]["height"] == 1080
        assert call_kwargs["locale"] == "ko-KR"
        assert call_kwargs["timezone_id"] == "Asia/Seoul"
        assert ctx is context_mock

    @pytest.mark.asyncio
    async def test_viewport_jitter_in_range(self) -> None:
        browser = MagicMock()
        context_mock = MagicMock()
        context_mock.add_init_script = AsyncMock()
        browser.new_context = AsyncMock(return_value=context_mock)

        config = StealthConfig(
            randomize_viewport=True,
            viewport_jitter_px=20,
        )

        await create_stealth_context(browser, config)

        call_kwargs = browser.new_context.call_args.kwargs
        vp = call_kwargs["viewport"]
        assert 1900 <= vp["width"] <= 1940
        assert 1060 <= vp["height"] <= 1100

    @pytest.mark.asyncio
    async def test_auto_selects_user_agent_when_none(self) -> None:
        browser = MagicMock()
        context_mock = MagicMock()
        context_mock.add_init_script = AsyncMock()
        browser.new_context = AsyncMock(return_value=context_mock)

        config = StealthConfig(user_agent=None)

        await create_stealth_context(browser, config)

        call_kwargs = browser.new_context.call_args.kwargs
        assert call_kwargs["user_agent"] in _USER_AGENTS

    @pytest.mark.asyncio
    async def test_patches_applied_after_context_creation(self) -> None:
        browser = MagicMock()
        context_mock = MagicMock()
        context_mock.add_init_script = AsyncMock()
        browser.new_context = AsyncMock(return_value=context_mock)

        config = StealthConfig(level="standard")

        await create_stealth_context(browser, config)

        assert context_mock.add_init_script.call_count == 5


class TestUserAgents:
    def test_three_ua_strings(self) -> None:
        assert len(_USER_AGENTS) == 3

    def test_all_contain_chrome(self) -> None:
        for ua in _USER_AGENTS:
            assert "Chrome" in ua

    def test_platforms_covered(self) -> None:
        platforms = " ".join(_USER_AGENTS)
        assert "Windows" in platforms
        assert "Macintosh" in platforms
        assert "Linux" in platforms
