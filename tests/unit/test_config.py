"""Tests for src.core.config — YAML → dataclass configuration loader."""
from __future__ import annotations

import pytest
import yaml

from src.core.config import (
    BehaviorConfig,
    EngineConfig,
    NavigationConfig,
    RetryConfig,
    StealthConfig,
    _parse_config,
    load_config,
)


class TestStealthConfig:
    def test_defaults(self) -> None:
        cfg = StealthConfig()
        assert cfg.enabled is True
        assert cfg.level == "standard"
        assert cfg.locale == "ko-KR"

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid stealth level"):
            StealthConfig(level="turbo")

    @pytest.mark.parametrize("level", ["minimal", "standard", "aggressive"])
    def test_valid_levels(self, level: str) -> None:
        cfg = StealthConfig(level=level)
        assert cfg.level == level


class TestBehaviorConfig:
    def test_defaults(self) -> None:
        cfg = BehaviorConfig()
        assert cfg.typing_delay_ms == (50, 150)
        assert cfg.click_delay_ms == (100, 300)
        assert cfg.step_delay_jitter == 0.3


class TestEngineConfig:
    def test_default_construction(self) -> None:
        cfg = EngineConfig()
        assert isinstance(cfg.stealth, StealthConfig)
        assert isinstance(cfg.behavior, BehaviorConfig)
        assert isinstance(cfg.navigation, NavigationConfig)
        assert isinstance(cfg.retry, RetryConfig)


class TestLoadConfig:
    def test_loads_default_settings(self) -> None:
        cfg = load_config("config/settings.yaml")
        assert cfg.stealth.enabled is True
        assert cfg.stealth.level == "standard"
        assert cfg.retry.backoff_base_ms == 500
        assert cfg.navigation.homepage_first is True
        assert cfg.behavior.enabled is True

    def test_missing_file_returns_defaults(self, tmp_path: object) -> None:
        cfg = load_config("/nonexistent/path/settings.yaml")
        assert isinstance(cfg, EngineConfig)
        assert cfg.stealth.level == "standard"

    def test_programmatic_override(self) -> None:
        cfg = EngineConfig(
            stealth=StealthConfig(level="aggressive"),
            retry=RetryConfig(backoff_base_ms=1000),
        )
        assert cfg.stealth.level == "aggressive"
        assert cfg.retry.backoff_base_ms == 1000

    def test_parse_from_dict(self) -> None:
        raw = {
            "stealth": {"level": "minimal", "enabled": False},
            "retry": {"backoff_base_ms": 250, "enable_replanning": False},
        }
        cfg = _parse_config(raw)
        assert cfg.stealth.level == "minimal"
        assert cfg.stealth.enabled is False
        assert cfg.retry.backoff_base_ms == 250
        assert cfg.retry.enable_replanning is False

    def test_yaml_roundtrip(self, tmp_path: object) -> None:
        """Write YAML, load it, verify values."""
        import tempfile
        from pathlib import Path

        data = {
            "stealth": {"enabled": True, "level": "aggressive"},
            "human_behavior": {"typing_delay_ms": [30, 100]},
            "navigation": {"rate_limit_per_domain_ms": 5000},
            "retry": {"jitter_ratio": 0.5},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(data, f)
            fpath = f.name

        cfg = load_config(fpath)
        Path(fpath).unlink()

        assert cfg.stealth.level == "aggressive"
        assert cfg.behavior.typing_delay_ms == (30, 100)
        assert cfg.navigation.rate_limit_ms == 5000
        assert cfg.retry.jitter_ratio == 0.5
