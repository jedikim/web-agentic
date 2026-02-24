"""Unified configuration loader — YAML → dataclass mapping.

Aggregates all engine configuration (stealth, behavior, navigation, retry)
into a single ``EngineConfig`` that can be loaded from ``config/settings.yaml``
or constructed programmatically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_SETTINGS_PATH = "config/settings.yaml"


# ── Stealth ──────────────────────────────────────────

_VALID_STEALTH_LEVELS = ("minimal", "standard", "aggressive")


@dataclass(frozen=True)
class StealthConfig:
    """Browser stealth configuration.

    Attributes:
        enabled: Whether stealth patches are applied.
        level: Stealth level — minimal | standard | aggressive.
        suppress_webdriver: Remove ``navigator.webdriver`` flag.
        suppress_chrome_runtime: Spoof ``chrome.runtime``.
        randomize_viewport: Add small viewport jitter.
        viewport_jitter_px: Maximum jitter pixels (each axis).
        user_agent: Custom user-agent string (None = auto-rotate).
        locale: Browser locale.
        timezone_id: Browser timezone.
    """

    enabled: bool = True
    level: str = "standard"
    suppress_webdriver: bool = True
    suppress_chrome_runtime: bool = True
    randomize_viewport: bool = True
    viewport_jitter_px: int = 10
    user_agent: str | None = None
    locale: str = "ko-KR"
    timezone_id: str = "Asia/Seoul"

    def __post_init__(self) -> None:
        if self.level not in _VALID_STEALTH_LEVELS:
            raise ValueError(
                f"Invalid stealth level {self.level!r}; "
                f"must be one of {_VALID_STEALTH_LEVELS}"
            )


# ── Human Behavior ───────────────────────────────────


@dataclass(frozen=True)
class BehaviorConfig:
    """Human-like behavior simulation configuration.

    Attributes:
        enabled: Whether human-behavior simulation is active.
        mouse_movement: Enable Bézier-curve mouse movement.
        typing_delay_ms: Per-character typing delay range (min, max).
        click_delay_ms: Pre-click hover delay range (min, max).
        step_delay_jitter: Fractional jitter applied to inter-step waits.
        scroll_smooth: Enable smooth incremental scrolling.
        scroll_step_px: Pixels per scroll increment.
    """

    enabled: bool = True
    mouse_movement: bool = True
    typing_delay_ms: tuple[int, int] = (50, 150)
    click_delay_ms: tuple[int, int] = (100, 300)
    step_delay_jitter: float = 0.3
    scroll_smooth: bool = True
    scroll_step_px: int = 100


# ── Navigation ───────────────────────────────────────


@dataclass(frozen=True)
class NavigationConfig:
    """Navigation intelligence configuration.

    Attributes:
        homepage_first: Visit root domain before deep URLs.
        respect_robots_txt: Honour robots.txt rules.
        rate_limit_ms: Minimum ms between navigations to the same domain.
        referrer_chain: Set previous page as Referer header.
    """

    homepage_first: bool = True
    respect_robots_txt: bool = True
    rate_limit_ms: int = 2000
    referrer_chain: bool = True


# ── Retry ────────────────────────────────────────────


@dataclass(frozen=True)
class RetryConfig:
    """Adaptive retry and replanning configuration.

    Attributes:
        backoff_base_ms: Base delay for exponential backoff.
        backoff_max_ms: Maximum backoff delay.
        jitter_ratio: Fractional jitter (± ratio * delay).
        max_consecutive_failures: Circuit-breaker threshold.
        enable_replanning: Allow LLM to replan remaining steps on failure.
    """

    backoff_base_ms: int = 500
    backoff_max_ms: int = 10_000
    jitter_ratio: float = 0.3
    max_consecutive_failures: int = 3
    enable_replanning: bool = True


# ── Aggregate Config ─────────────────────────────────


@dataclass
class EngineConfig:
    """Root configuration aggregating all sub-configs."""

    stealth: StealthConfig = field(default_factory=StealthConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


# ── Loader ───────────────────────────────────────────


def _to_tuple_int(val: Any) -> tuple[int, int]:
    """Convert a list/tuple value to a ``tuple[int, int]``."""
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return (int(val[0]), int(val[1]))
    return (int(val), int(val))


def load_config(path: str = _DEFAULT_SETTINGS_PATH) -> EngineConfig:
    """Load engine configuration from a YAML file.

    Missing sections fall back to dataclass defaults.

    Args:
        path: Path to the YAML settings file.

    Returns:
        A populated ``EngineConfig`` instance.
    """
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("Settings file not found: %s — using defaults", path)
        return EngineConfig()

    with config_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    return _parse_config(raw)


def _parse_config(raw: dict[str, Any]) -> EngineConfig:
    """Parse raw YAML dict into EngineConfig."""
    stealth_raw = raw.get("stealth", {})
    behavior_raw = raw.get("human_behavior", {})
    nav_raw = raw.get("navigation", {})
    retry_raw = raw.get("retry", {})

    stealth = StealthConfig(
        enabled=stealth_raw.get("enabled", True),
        level=stealth_raw.get("level", "standard"),
        suppress_webdriver=stealth_raw.get("suppress_webdriver", True),
        suppress_chrome_runtime=stealth_raw.get("suppress_chrome_runtime", True),
        randomize_viewport=stealth_raw.get("randomize_viewport", True),
        viewport_jitter_px=stealth_raw.get("viewport_jitter_px", 10),
        user_agent=stealth_raw.get("user_agent"),
        locale=stealth_raw.get("locale", "ko-KR"),
        timezone_id=stealth_raw.get("timezone_id", "Asia/Seoul"),
    ) if stealth_raw else StealthConfig()

    behavior = BehaviorConfig(
        enabled=behavior_raw.get("enabled", True),
        mouse_movement=behavior_raw.get("mouse_movement", True),
        typing_delay_ms=_to_tuple_int(
            behavior_raw.get("typing_delay_ms", [50, 150])
        ),
        click_delay_ms=_to_tuple_int(
            behavior_raw.get("click_delay_ms", [100, 300])
        ),
        step_delay_jitter=float(behavior_raw.get("step_delay_jitter_ratio", 0.3)),
        scroll_smooth=behavior_raw.get("scroll_smooth", True),
        scroll_step_px=behavior_raw.get("scroll_step_px", 100),
    ) if behavior_raw else BehaviorConfig()

    navigation = NavigationConfig(
        homepage_first=nav_raw.get("homepage_first", True),
        respect_robots_txt=nav_raw.get("respect_robots_txt", True),
        rate_limit_ms=nav_raw.get("rate_limit_per_domain_ms", 2000),
        referrer_chain=nav_raw.get("referrer_chain", True),
    ) if nav_raw else NavigationConfig()

    retry = RetryConfig(
        backoff_base_ms=retry_raw.get("backoff_base_ms", 500),
        backoff_max_ms=retry_raw.get("backoff_max_ms", 10_000),
        jitter_ratio=float(retry_raw.get("jitter_ratio", 0.3)),
        max_consecutive_failures=retry_raw.get("max_consecutive_failures", 3),
        enable_replanning=retry_raw.get("enable_replanning", True),
    ) if retry_raw else RetryConfig()

    return EngineConfig(
        stealth=stealth,
        behavior=behavior,
        navigation=navigation,
        retry=retry,
    )
