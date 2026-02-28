"""Unit tests for H(Human Handoff) — ``src.core.handoff``."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.core.handoff import (
    HandoffManager,
    HandoffNotFoundError,
    HandoffReason,
    HandoffRequest,
    HandoffResponse,
    HandoffTimeoutError,
)

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def manager() -> HandoffManager:
    """Create a fresh HandoffManager instance."""
    return HandoffManager()


# ── Test: HandoffReason Enum ─────────────────────────


class TestHandoffReasonEnum:
    """HandoffReason enum has the expected members and values."""

    def test_captcha_value(self) -> None:
        assert HandoffReason.CAPTCHA == "captcha"
        assert HandoffReason.CAPTCHA.value == "captcha"

    def test_auth_2fa_value(self) -> None:
        assert HandoffReason.AUTH_2FA == "2fa"
        assert HandoffReason.AUTH_2FA.value == "2fa"

    def test_payment_value(self) -> None:
        assert HandoffReason.PAYMENT == "payment"
        assert HandoffReason.PAYMENT.value == "payment"

    def test_age_verify_value(self) -> None:
        assert HandoffReason.AGE_VERIFY == "age_verify"
        assert HandoffReason.AGE_VERIFY.value == "age_verify"

    def test_custom_value(self) -> None:
        assert HandoffReason.CUSTOM == "custom"
        assert HandoffReason.CUSTOM.value == "custom"

    def test_all_reasons_count(self) -> None:
        """There are exactly 5 handoff reasons."""
        assert len(HandoffReason) == 5

    def test_is_str_enum(self) -> None:
        """HandoffReason members are also strings."""
        for reason in HandoffReason:
            assert isinstance(reason, str)


# ── Test: HandoffRequest Dataclass ───────────────────


class TestHandoffRequestDataclass:
    """HandoffRequest has the expected fields and defaults."""

    def test_required_fields(self) -> None:
        req = HandoffRequest(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test Page",
        )
        assert req.reason == HandoffReason.CAPTCHA
        assert req.url == "https://example.com"
        assert req.title == "Test Page"

    def test_default_fields(self) -> None:
        req = HandoffRequest(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        assert req.screenshot is None
        assert req.message == ""
        assert req.metadata == {}
        assert req.created_at == ""
        assert req.request_id == ""

    def test_all_fields(self) -> None:
        req = HandoffRequest(
            reason=HandoffReason.PAYMENT,
            url="https://shop.com/checkout",
            title="Checkout",
            screenshot=b"png_data",
            message="Payment required",
            metadata={"amount": 50000},
            created_at="2025-01-01T00:00:00+00:00",
            request_id="abc-123",
        )
        assert req.screenshot == b"png_data"
        assert req.message == "Payment required"
        assert req.metadata["amount"] == 50000
        assert req.created_at == "2025-01-01T00:00:00+00:00"
        assert req.request_id == "abc-123"


# ── Test: HandoffResponse Dataclass ──────────────────


class TestHandoffResponseDataclass:
    """HandoffResponse has the expected fields."""

    def test_required_fields(self) -> None:
        resp = HandoffResponse(request_id="abc", resolved=True)
        assert resp.request_id == "abc"
        assert resp.resolved is True
        assert resp.action_taken == ""
        assert resp.metadata == {}

    def test_all_fields(self) -> None:
        resp = HandoffResponse(
            request_id="xyz",
            resolved=True,
            action_taken="Solved CAPTCHA",
            metadata={"solver": "human"},
        )
        assert resp.action_taken == "Solved CAPTCHA"
        assert resp.metadata["solver"] == "human"


# ── Test: request_handoff ────────────────────────────


class TestRequestHandoff:
    """request_handoff creates a HandoffRequest with UUID and timestamp."""

    @pytest.mark.asyncio
    async def test_creates_request_with_uuid(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        assert req.request_id != ""
        # UUID4 format: 8-4-4-4-12 hex chars.
        parts = req.request_id.split("-")
        assert len(parts) == 5

    @pytest.mark.asyncio
    async def test_creates_request_with_timestamp(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.AUTH_2FA,
            url="https://example.com/login",
            title="Login",
        )
        assert req.created_at != ""
        # Should be ISO format.
        assert "T" in req.created_at

    @pytest.mark.asyncio
    async def test_request_fields_match_arguments(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.PAYMENT,
            url="https://shop.com/pay",
            title="Payment",
            screenshot=b"img",
            message="Complete payment",
            metadata={"total": 100},
        )
        assert req.reason == HandoffReason.PAYMENT
        assert req.url == "https://shop.com/pay"
        assert req.title == "Payment"
        assert req.screenshot == b"img"
        assert req.message == "Complete payment"
        assert req.metadata["total"] == 100

    @pytest.mark.asyncio
    async def test_request_appears_in_pending(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].request_id == req.request_id

    @pytest.mark.asyncio
    async def test_request_appears_in_history(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        history = manager.get_history()
        assert len(history) == 1
        assert history[0][0].request_id == req.request_id
        assert history[0][1] is None  # Not yet resolved.


# ── Test: wait_for_resolution ────────────────────────


class TestWaitForResolution:
    """wait_for_resolution blocks until resolve() or timeout."""

    @pytest.mark.asyncio
    async def test_returns_after_resolve(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )

        async def _resolve_soon() -> None:
            await asyncio.sleep(0.05)
            await manager.resolve(req.request_id, action_taken="Solved")

        asyncio.get_event_loop().create_task(_resolve_soon())
        response = await manager.wait_for_resolution(req.request_id, timeout_s=5.0)

        assert response.resolved is True
        assert response.request_id == req.request_id
        assert response.action_taken == "Solved"

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.AUTH_2FA,
            url="https://example.com",
            title="Test",
        )
        with pytest.raises(HandoffTimeoutError):
            await manager.wait_for_resolution(req.request_id, timeout_s=0.05)

    @pytest.mark.asyncio
    async def test_unknown_request_id_raises_error(self, manager: HandoffManager) -> None:
        with pytest.raises(HandoffNotFoundError):
            await manager.wait_for_resolution("nonexistent-id")

    @pytest.mark.asyncio
    async def test_already_resolved_returns_immediately(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        await manager.resolve(req.request_id, action_taken="Done")

        # Calling wait after already resolved should return the response.
        response = await manager.wait_for_resolution(req.request_id, timeout_s=1.0)
        assert response.resolved is True


# ── Test: resolve ────────────────────────────────────


class TestResolve:
    """resolve() marks request as resolved and clears pending."""

    @pytest.mark.asyncio
    async def test_resolve_clears_pending(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        assert len(manager.get_pending()) == 1
        await manager.resolve(req.request_id, action_taken="Solved")
        assert len(manager.get_pending()) == 0

    @pytest.mark.asyncio
    async def test_resolve_updates_history(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )
        await manager.resolve(req.request_id, action_taken="Solved CAPTCHA")

        history = manager.get_history()
        assert len(history) == 1
        assert history[0][1] is not None
        assert history[0][1].resolved is True
        assert history[0][1].action_taken == "Solved CAPTCHA"

    @pytest.mark.asyncio
    async def test_resolve_unknown_id_raises_error(self, manager: HandoffManager) -> None:
        with pytest.raises(HandoffNotFoundError):
            await manager.resolve("nonexistent-id")

    @pytest.mark.asyncio
    async def test_resolve_with_metadata(self, manager: HandoffManager) -> None:
        req = await manager.request_handoff(
            reason=HandoffReason.PAYMENT,
            url="https://shop.com",
            title="Pay",
        )
        await manager.resolve(
            req.request_id,
            action_taken="Paid",
            metadata={"receipt_id": "R123"},
        )
        response = await manager.wait_for_resolution(req.request_id)
        assert response.metadata["receipt_id"] == "R123"


# ── Test: get_pending / get_history ──────────────────


class TestGetPendingAndHistory:
    """get_pending and get_history track all requests correctly."""

    @pytest.mark.asyncio
    async def test_get_pending_shows_only_unresolved(self, manager: HandoffManager) -> None:
        req1 = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com/a",
            title="A",
        )
        req2 = await manager.request_handoff(
            reason=HandoffReason.AUTH_2FA,
            url="https://example.com/b",
            title="B",
        )
        await manager.resolve(req1.request_id)

        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].request_id == req2.request_id

    @pytest.mark.asyncio
    async def test_get_history_includes_all(self, manager: HandoffManager) -> None:
        await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com/a",
            title="A",
        )
        await manager.request_handoff(
            reason=HandoffReason.PAYMENT,
            url="https://example.com/b",
            title="B",
        )
        history = manager.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_empty_pending_initially(self, manager: HandoffManager) -> None:
        assert manager.get_pending() == []

    @pytest.mark.asyncio
    async def test_empty_history_initially(self, manager: HandoffManager) -> None:
        assert manager.get_history() == []


# ── Test: Callback Notification ──────────────────────


class TestCallbackNotification:
    """on_handoff registers callbacks that fire on new requests."""

    @pytest.mark.asyncio
    async def test_callback_called_on_handoff(self, manager: HandoffManager) -> None:
        mock_cb = MagicMock()
        manager.on_handoff(mock_cb)

        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )

        mock_cb.assert_called_once_with(req)

    @pytest.mark.asyncio
    async def test_multiple_callbacks(self, manager: HandoffManager) -> None:
        cb1 = MagicMock()
        cb2 = MagicMock()
        manager.on_handoff(cb1)
        manager.on_handoff(cb2)

        await manager.request_handoff(
            reason=HandoffReason.PAYMENT,
            url="https://shop.com",
            title="Pay",
        )

        cb1.assert_called_once()
        cb2.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break(self, manager: HandoffManager) -> None:
        """If a callback raises, other callbacks still fire and the request is created."""
        bad_cb = MagicMock(side_effect=RuntimeError("callback error"))
        good_cb = MagicMock()
        manager.on_handoff(bad_cb)
        manager.on_handoff(good_cb)

        req = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com",
            title="Test",
        )

        bad_cb.assert_called_once()
        good_cb.assert_called_once()
        assert req.request_id != ""


# ── Test: Multiple Simultaneous Handoffs ─────────────


class TestMultipleSimultaneousHandoffs:
    """Multiple handoff requests can be active and resolved independently."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self, manager: HandoffManager) -> None:
        req1 = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://a.com",
            title="A",
        )
        req2 = await manager.request_handoff(
            reason=HandoffReason.AUTH_2FA,
            url="https://b.com",
            title="B",
        )
        req3 = await manager.request_handoff(
            reason=HandoffReason.PAYMENT,
            url="https://c.com",
            title="C",
        )

        assert len(manager.get_pending()) == 3

        # Resolve in different order.
        await manager.resolve(req2.request_id, action_taken="2FA done")
        assert len(manager.get_pending()) == 2

        await manager.resolve(req1.request_id, action_taken="CAPTCHA solved")
        assert len(manager.get_pending()) == 1

        await manager.resolve(req3.request_id, action_taken="Payment made")
        assert len(manager.get_pending()) == 0

    @pytest.mark.asyncio
    async def test_concurrent_wait_and_resolve(self, manager: HandoffManager) -> None:
        """Two requests can be waited on and resolved concurrently."""
        req1 = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://a.com",
            title="A",
        )
        req2 = await manager.request_handoff(
            reason=HandoffReason.AUTH_2FA,
            url="https://b.com",
            title="B",
        )

        async def _resolve_both() -> None:
            await asyncio.sleep(0.05)
            await manager.resolve(req1.request_id, action_taken="Solved 1")
            await manager.resolve(req2.request_id, action_taken="Solved 2")

        asyncio.get_event_loop().create_task(_resolve_both())

        resp1, resp2 = await asyncio.gather(
            manager.wait_for_resolution(req1.request_id, timeout_s=5.0),
            manager.wait_for_resolution(req2.request_id, timeout_s=5.0),
        )

        assert resp1.resolved is True
        assert resp1.action_taken == "Solved 1"
        assert resp2.resolved is True
        assert resp2.action_taken == "Solved 2"

    @pytest.mark.asyncio
    async def test_unique_request_ids(self, manager: HandoffManager) -> None:
        """Each handoff request gets a unique request_id."""
        requests = []
        for _ in range(10):
            req = await manager.request_handoff(
                reason=HandoffReason.CUSTOM,
                url="https://example.com",
                title="Test",
            )
            requests.append(req)

        ids = [r.request_id for r in requests]
        assert len(set(ids)) == 10  # All unique.
