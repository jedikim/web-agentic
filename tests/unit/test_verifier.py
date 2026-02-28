"""Unit tests for V(Verifier) module.

Tests cover every verification type with success, failure, timeout, and
edge-case scenarios using mocked Playwright Page objects.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from src.core.types import VerifyCondition
from src.core.verifier import Verifier

# ── Helpers ──────────────────────────────────────────


def _make_page(url: str = "https://example.com") -> MagicMock:
    """Create a mock Playwright Page with a configurable URL property."""
    page = MagicMock()
    type(page).url = PropertyMock(return_value=url)
    page.locator = MagicMock()
    page.inner_text = AsyncMock(return_value="")
    page.wait_for_load_state = AsyncMock()
    return page


def _make_locator(*, visible: bool = True, raise_on_wait: bool = False) -> MagicMock:
    """Create a mock locator that resolves or raises on wait_for."""
    locator = MagicMock()
    if raise_on_wait:
        locator.wait_for = AsyncMock(side_effect=TimeoutError("Timed out"))
    else:
        locator.wait_for = AsyncMock()
    return locator


@pytest.fixture
def verifier() -> Verifier:
    return Verifier()


# ── url_changed ──────────────────────────────────────


@pytest.mark.asyncio
async def test_url_changed_success(verifier: Verifier) -> None:
    """URL actually changed from the previous value."""
    page = _make_page(url="https://example.com/new-page")
    condition = VerifyCondition(type="url_changed", value="https://example.com", timeout_ms=500)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "changed" in result.message
    assert result.details["previous_url"] == "https://example.com"
    assert result.details["current_url"] == "https://example.com/new-page"


@pytest.mark.asyncio
async def test_url_changed_failure_same_url(verifier: Verifier) -> None:
    """URL stayed the same — verification should fail."""
    page = _make_page(url="https://example.com")
    condition = VerifyCondition(type="url_changed", value="https://example.com", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "did not change" in result.message


@pytest.mark.asyncio
async def test_url_changed_missing_value(verifier: Verifier) -> None:
    """No previous URL provided — should fail with helpful message."""
    page = _make_page()
    condition = VerifyCondition(type="url_changed", value="", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "requires" in result.message


@pytest.mark.asyncio
async def test_url_changed_eventually(verifier: Verifier) -> None:
    """URL changes after a short delay — polling should catch it."""
    page = _make_page(url="https://example.com")

    # Simulate URL changing after a few polls
    call_count = 0
    original_url = "https://example.com"
    new_url = "https://example.com/navigated"

    def dynamic_url() -> str:
        nonlocal call_count
        call_count += 1
        return new_url if call_count > 3 else original_url

    type(page).url = PropertyMock(side_effect=dynamic_url)
    condition = VerifyCondition(type="url_changed", value=original_url, timeout_ms=2000)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert result.details["current_url"] == new_url


# ── url_contains ─────────────────────────────────────


@pytest.mark.asyncio
async def test_url_contains_success(verifier: Verifier) -> None:
    """URL contains the expected substring."""
    page = _make_page(url="https://example.com/search?q=shoes")
    condition = VerifyCondition(type="url_contains", value="search?q=shoes", timeout_ms=500)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "contains" in result.message


@pytest.mark.asyncio
async def test_url_contains_failure(verifier: Verifier) -> None:
    """URL does not contain the expected substring."""
    page = _make_page(url="https://example.com/home")
    condition = VerifyCondition(type="url_contains", value="search?q=", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "does not contain" in result.message


@pytest.mark.asyncio
async def test_url_contains_missing_value(verifier: Verifier) -> None:
    """Empty expected substring — should fail."""
    page = _make_page()
    condition = VerifyCondition(type="url_contains", value="", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "requires" in result.message


# ── element_visible ──────────────────────────────────


@pytest.mark.asyncio
async def test_element_visible_success(verifier: Verifier) -> None:
    """Element is visible on the page."""
    page = _make_page()
    locator = _make_locator(visible=True)
    page.locator.return_value = locator
    condition = VerifyCondition(type="element_visible", value="#submit-btn", timeout_ms=500)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "visible" in result.message
    page.locator.assert_called_once_with("#submit-btn")
    locator.wait_for.assert_awaited_once_with(state="visible", timeout=500)


@pytest.mark.asyncio
async def test_element_visible_failure_not_found(verifier: Verifier) -> None:
    """Element not found or not visible — verification fails."""
    page = _make_page()
    locator = _make_locator(raise_on_wait=True)
    page.locator.return_value = locator
    condition = VerifyCondition(type="element_visible", value=".missing-class", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "not visible" in result.message


@pytest.mark.asyncio
async def test_element_visible_missing_selector(verifier: Verifier) -> None:
    """No selector provided — should fail with helpful message."""
    page = _make_page()
    condition = VerifyCondition(type="element_visible", value="", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "requires" in result.message


# ── element_gone ─────────────────────────────────────


@pytest.mark.asyncio
async def test_element_gone_success(verifier: Verifier) -> None:
    """Element is gone (hidden) — verification succeeds."""
    page = _make_page()
    locator = _make_locator(visible=False)
    page.locator.return_value = locator
    condition = VerifyCondition(type="element_gone", value=".popup-overlay", timeout_ms=500)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "gone" in result.message
    locator.wait_for.assert_awaited_once_with(state="hidden", timeout=500)


@pytest.mark.asyncio
async def test_element_gone_failure_still_visible(verifier: Verifier) -> None:
    """Element is still visible — verification fails."""
    page = _make_page()
    locator = _make_locator(raise_on_wait=True)
    page.locator.return_value = locator
    condition = VerifyCondition(type="element_gone", value=".popup-overlay", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "still visible" in result.message


@pytest.mark.asyncio
async def test_element_gone_missing_selector(verifier: Verifier) -> None:
    """No selector provided — should fail."""
    page = _make_page()
    condition = VerifyCondition(type="element_gone", value="", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "requires" in result.message


# ── text_present ─────────────────────────────────────


@pytest.mark.asyncio
async def test_text_present_success(verifier: Verifier) -> None:
    """Expected text is present on the page."""
    page = _make_page()
    page.inner_text = AsyncMock(return_value="Welcome to Example Shop. 1234 results found.")
    condition = VerifyCondition(type="text_present", value="1234 results", timeout_ms=500)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "found" in result.message


@pytest.mark.asyncio
async def test_text_present_failure(verifier: Verifier) -> None:
    """Expected text is not on the page."""
    page = _make_page()
    page.inner_text = AsyncMock(return_value="Nothing here")
    condition = VerifyCondition(type="text_present", value="results found", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "not found" in result.message


@pytest.mark.asyncio
async def test_text_present_empty_page(verifier: Verifier) -> None:
    """Page body has no text — inner_text raises."""
    page = _make_page()
    page.inner_text = AsyncMock(side_effect=Exception("No body element"))
    condition = VerifyCondition(type="text_present", value="anything", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "not found" in result.message


@pytest.mark.asyncio
async def test_text_present_missing_value(verifier: Verifier) -> None:
    """Empty expected text — should fail."""
    page = _make_page()
    condition = VerifyCondition(type="text_present", value="", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "requires" in result.message


@pytest.mark.asyncio
async def test_text_present_eventually(verifier: Verifier) -> None:
    """Text appears after a few polls — should succeed."""
    page = _make_page()

    call_count = 0

    async def dynamic_inner_text(selector: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count > 3:
            return "Search results: 42 items"
        return "Loading..."

    page.inner_text = dynamic_inner_text
    condition = VerifyCondition(type="text_present", value="42 items", timeout_ms=2000)

    result = await verifier.verify(condition, page)

    assert result.success is True


# ── network_idle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_network_idle_success(verifier: Verifier) -> None:
    """Network becomes idle within timeout."""
    page = _make_page()
    page.wait_for_load_state = AsyncMock()
    condition = VerifyCondition(type="network_idle", timeout_ms=3000)

    result = await verifier.verify(condition, page)

    assert result.success is True
    assert "idle" in result.message
    page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=3000)


@pytest.mark.asyncio
async def test_network_idle_timeout(verifier: Verifier) -> None:
    """Network does not become idle — times out."""
    page = _make_page()
    page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("still loading"))
    condition = VerifyCondition(type="network_idle", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "not idle" in result.message


# ── Unknown type ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_verification_type(verifier: Verifier) -> None:
    """Unknown verification type returns a clear failure."""
    page = _make_page()
    condition = VerifyCondition(type="magic_check", value="abracadabra", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "Unknown" in result.message
    assert result.details["type"] == "magic_check"


# ── Generic exception handling ───────────────────────


@pytest.mark.asyncio
async def test_handler_unexpected_exception(verifier: Verifier) -> None:
    """An unexpected exception in a handler is caught gracefully."""
    page = _make_page()

    # Force an unexpected RuntimeError inside url_changed by making page.url raise
    type(page).url = PropertyMock(side_effect=RuntimeError("browser crashed"))
    condition = VerifyCondition(type="url_changed", value="https://old.com", timeout_ms=100)

    result = await verifier.verify(condition, page)

    assert result.success is False
    assert "error" in result.message.lower()


# ── Protocol conformance ─────────────────────────────


@pytest.mark.asyncio
async def test_verifier_satisfies_iverifier_protocol() -> None:
    """Verifier class satisfies the IVerifier Protocol structurally."""

    v = Verifier()
    # Structural subtyping check — must have async verify(condition, page)
    assert hasattr(v, "verify")
    assert asyncio.iscoroutinefunction(v.verify)
