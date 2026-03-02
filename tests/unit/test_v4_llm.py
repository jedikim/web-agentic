"""Tests for the v4 LLM routing system (router, routing_policy, cost_monitor)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.llm.cost_monitor import BudgetExceededError, CostMonitor
from src.llm.router import (
    VENDOR_MODELS,
    assert_model_lifecycle,
    build_model_registry,
    detect_vendor,
)
from src.llm.routing_policy import ROUTING_POLICY

# ── detect_vendor ────────────────────────────────────


def test_detect_vendor_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """GEMINI_API_KEY set -> vendor is 'gemini'."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert detect_vendor() == "gemini"


def test_detect_vendor_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY set (no Gemini keys) -> vendor is 'openai'."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert detect_vendor() == "openai"


def test_detect_vendor_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No API keys set -> RuntimeError."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY or OPENAI_API_KEY"):
        detect_vendor()


# ── build_model_registry ─────────────────────────────


def test_build_model_registry_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini vendor -> correct model names from VENDOR_MODELS."""
    monkeypatch.delenv("MODEL_FAST", raising=False)
    monkeypatch.delenv("MODEL_STRONG", raising=False)
    monkeypatch.delenv("MODEL_CODEGEN", raising=False)
    monkeypatch.delenv("MODEL_VISION", raising=False)
    registry = build_model_registry(vendor="gemini")
    assert registry == VENDOR_MODELS["gemini"]


def test_build_model_registry_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI vendor -> correct model names from VENDOR_MODELS."""
    monkeypatch.delenv("MODEL_FAST", raising=False)
    monkeypatch.delenv("MODEL_STRONG", raising=False)
    monkeypatch.delenv("MODEL_CODEGEN", raising=False)
    monkeypatch.delenv("MODEL_VISION", raising=False)
    registry = build_model_registry(vendor="openai")
    assert registry == VENDOR_MODELS["openai"]


def test_model_registry_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODEL_FAST env var overrides default model for 'fast' alias."""
    monkeypatch.setenv("MODEL_FAST", "gemini/custom-fast-model")
    monkeypatch.delenv("MODEL_STRONG", raising=False)
    monkeypatch.delenv("MODEL_CODEGEN", raising=False)
    monkeypatch.delenv("MODEL_VISION", raising=False)
    registry = build_model_registry(vendor="gemini")
    assert registry["fast"] == "gemini/custom-fast-model"
    # Other aliases remain default
    assert registry["strong"] == VENDOR_MODELS["gemini"]["strong"]


# ── assert_model_lifecycle ───────────────────────────


def test_assert_model_lifecycle_ok() -> None:
    """Non-sunset model passes without error."""
    assert_model_lifecycle("gemini/gemini-3-flash-preview")


def test_assert_model_lifecycle_expired() -> None:
    """Sunset model with past date raises RuntimeError."""
    with patch("src.llm.router.date") as mock_date:
        mock_date.today.return_value = date(2027, 1, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        with pytest.raises(RuntimeError, match="Model sunset reached"):
            assert_model_lifecycle("gemini/gemini-2.0-flash")


# ── ROUTING_POLICY (routing_policy.py) ───────────────


def test_routing_policy_keys() -> None:
    """All expected task types exist in ROUTING_POLICY."""
    expected = {
        "recon_synthesize",
        "codegen",
        "codegen_complex",
        "selector_fix",
        "failure_analysis",
        "vision_analysis",
    }
    assert set(ROUTING_POLICY.keys()) == expected


def test_routing_policy_defaults() -> None:
    """Verify primary alias for each task type."""
    assert ROUTING_POLICY["recon_synthesize"].alias == "fast"
    assert ROUTING_POLICY["codegen"].alias == "codegen"
    assert ROUTING_POLICY["codegen_complex"].alias == "codegen"
    assert ROUTING_POLICY["selector_fix"].alias == "fast"
    assert ROUTING_POLICY["failure_analysis"].alias == "strong"
    assert ROUTING_POLICY["vision_analysis"].alias == "vision"


# ── CostMonitor ──────────────────────────────────────


def test_estimate_cost() -> None:
    """Known model -> cost in expected range."""
    monitor = CostMonitor()
    cost = monitor.estimate_cost(
        "gemini/gemini-3-flash-preview",
        input_tokens=1000,
        output_tokens=500,
    )
    # input: 1000/1M * 0.10 = 0.0001, output: 500/1M * 0.40 = 0.0002
    assert 0.0001 < cost < 0.001


def test_record_increments() -> None:
    """record() increments total_cost and total_calls."""
    monitor = CostMonitor()
    assert monitor.total_calls == 0
    assert monitor.total_cost_usd == 0.0

    monitor.record(
        "gemini/gemini-3-flash-preview", input_tokens=1000, output_tokens=500
    )
    assert monitor.total_calls == 1
    assert monitor.total_cost_usd > 0.0

    prev_cost = monitor.total_cost_usd
    monitor.record(
        "gemini/gemini-3-flash-preview", input_tokens=2000, output_tokens=1000
    )
    assert monitor.total_calls == 2
    assert monitor.total_cost_usd > prev_cost


def test_check_budget_ok() -> None:
    """Under budget -> no error."""
    monitor = CostMonitor(budget_usd=1.0)
    monitor.record(
        "gemini/gemini-3-flash-preview", input_tokens=1000, output_tokens=500
    )
    monitor.check_budget()  # should not raise


def test_check_budget_exceeded() -> None:
    """Over budget -> BudgetExceededError."""
    monitor = CostMonitor(budget_usd=0.0001)
    # Record enough to exceed tiny budget
    monitor.record(
        "gemini/gemini-3.1-pro-preview", input_tokens=100_000, output_tokens=50_000
    )
    with pytest.raises(BudgetExceededError, match="Budget exceeded"):
        monitor.check_budget()


def test_remaining_usd() -> None:
    """remaining_usd reflects budget minus spent, floored at 0."""
    monitor = CostMonitor(budget_usd=1.0)
    assert monitor.remaining_usd == 1.0

    monitor.record(
        "gemini/gemini-3-flash-preview", input_tokens=1000, output_tokens=500
    )
    assert 0.0 < monitor.remaining_usd < 1.0

    # Overspend -> remaining clamps to 0
    monitor_tiny = CostMonitor(budget_usd=0.0)
    monitor_tiny.record(
        "gemini/gemini-3-flash-preview", input_tokens=1000, output_tokens=500
    )
    assert monitor_tiny.remaining_usd == 0.0


def test_reset() -> None:
    """reset() clears all tracking."""
    monitor = CostMonitor()
    monitor.record(
        "gemini/gemini-3-flash-preview", input_tokens=5000, output_tokens=2000
    )
    assert monitor.total_calls == 1
    assert monitor.total_cost_usd > 0.0
    assert len(monitor.records) == 1

    monitor.reset()
    assert monitor.total_calls == 0
    assert monitor.total_cost_usd == 0.0
    assert len(monitor.records) == 0
