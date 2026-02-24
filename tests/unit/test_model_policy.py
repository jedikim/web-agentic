"""Unit tests for the evolution model policy module."""
from __future__ import annotations

import pytest

from src.evolution.model_policy import (
    DEFAULT_AUTOMATION_MODEL,
    DEFAULT_CODING_MODEL,
    is_flash_model,
    resolve_evolution_model_policy,
)

# ── defaults ────────────────────────────────────────


def test_defaults() -> None:
    """With no overrides the built-in defaults are used."""
    policy = resolve_evolution_model_policy(env={})
    assert policy.coding_model == DEFAULT_CODING_MODEL
    assert policy.automation_model == DEFAULT_AUTOMATION_MODEL


# ── explicit overrides ──────────────────────────────


def test_custom_coding_model() -> None:
    policy = resolve_evolution_model_policy(
        coding_model="gemini-3-pro-preview", env={}
    )
    assert policy.coding_model == "gemini-3-pro-preview"
    assert policy.automation_model == DEFAULT_AUTOMATION_MODEL


def test_custom_automation_model() -> None:
    policy = resolve_evolution_model_policy(
        automation_model="gemini-2-flash", env={}
    )
    assert policy.coding_model == DEFAULT_CODING_MODEL
    assert policy.automation_model == "gemini-2-flash"


# ── env override ────────────────────────────────────


def test_env_override() -> None:
    env = {
        "EVOLUTION_CODING_MODEL": "gemini-3-pro-preview",
        "EVOLUTION_AUTOMATION_MODEL": "gemini-2-flash",
    }
    policy = resolve_evolution_model_policy(env=env)
    assert policy.coding_model == "gemini-3-pro-preview"
    assert policy.automation_model == "gemini-2-flash"


# ── explicit params override env ────────────────────


def test_explicit_overrides_env() -> None:
    env = {
        "EVOLUTION_CODING_MODEL": "gemini-3-pro-preview",
        "EVOLUTION_AUTOMATION_MODEL": "gemini-2-flash",
    }
    policy = resolve_evolution_model_policy(
        coding_model="custom-pro-v5",
        automation_model="custom-flash-v5",
        env=env,
    )
    assert policy.coding_model == "custom-pro-v5"
    assert policy.automation_model == "custom-flash-v5"


# ── validation errors ───────────────────────────────


def test_flash_model_as_coding_raises() -> None:
    with pytest.raises(ValueError, match="coding model must be a high-quality"):
        resolve_evolution_model_policy(coding_model="gemini-3-flash-preview", env={})


def test_non_flash_as_automation_raises() -> None:
    with pytest.raises(ValueError, match="automation model must use a fast flash-tier"):
        resolve_evolution_model_policy(automation_model="gemini-3.1-pro-preview", env={})


# ── is_flash_model helper ───────────────────────────


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-3-flash-preview", True),
        ("gemini-2-flash", True),
        ("GEMINI-FLASH-MEGA", True),
        ("gemini-3.1-pro-preview", False),
        ("gpt-4o", False),
        ("claude-opus-4", False),
    ],
)
def test_is_flash_model_helper(model: str, expected: bool) -> None:
    assert is_flash_model(model) is expected
