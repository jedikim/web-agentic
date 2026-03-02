"""Change detection — 3-signal synthesis for site drift monitoring."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.kb.manager import KBManager
from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)

# ── Signal weights ──

_W_SELECTOR = 0.5
_W_AX_TREE = 0.3
_W_API = 0.2

# ── Thresholds ──

THRESHOLD_RECON = 0.45
THRESHOLD_PATCH = 0.20


@runtime_checkable
class IBrowser(Protocol):
    """Minimal browser interface for change detection."""

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the page context."""
        ...

    async def query_selector_all(self, selector: str) -> list[Any]:
        """Return all elements matching a CSS selector."""
        ...

    async def accessibility_snapshot(self) -> dict[str, Any]:
        """Return the accessibility tree as a dict."""
        ...

    async def url(self) -> str:
        """Return the current page URL."""
        ...


@dataclass
class SignalDetail:
    """Detail for a single change-detection signal."""

    name: str = ""
    weight: float = 0.0
    raw_score: float = 0.0  # 0.0 = no change, 1.0 = completely changed
    weighted_score: float = 0.0
    detail: str = ""


@dataclass
class ChangeDetectionResult:
    """Combined change detection result."""

    score: float = 0.0  # 0.0 = unchanged, 1.0 = completely changed
    action: str = "none"  # "recon" | "patch" | "none"
    signal_details: list[SignalDetail] = field(default_factory=list)

    @property
    def needs_recon(self) -> bool:
        return self.action == "recon"

    @property
    def needs_patch(self) -> bool:
        return self.action == "patch"


class ChangeDetector:
    """Detect site changes via 3-signal synthesis.

    Signals:
        1. Selector survival rate (weight 0.5): test top-N selectors.
        2. AX tree diff (weight 0.3): compare current vs stored hash.
        3. API schema diff (weight 0.2): compare API endpoints.

    Combined score:
        >= 0.45 -> full recon
        >= 0.20 -> selector patch
        < 0.20  -> no change
    """

    def __init__(self, top_n_selectors: int = 10) -> None:
        self._top_n = top_n_selectors

    async def detect(
        self,
        domain: str,
        browser: IBrowser,
        kb: KBManager,
    ) -> ChangeDetectionResult:
        """Run 3-signal change detection.

        Args:
            domain: Site domain.
            browser: Browser instance with an open page.
            kb: Knowledge Base manager.

        Returns:
            ChangeDetectionResult with combined score and action.
        """
        profile = kb.load_profile(domain)
        if not profile:
            return ChangeDetectionResult(
                score=1.0,
                action="recon",
                signal_details=[
                    SignalDetail(
                        name="no_profile",
                        detail="No profile in KB; full recon required.",
                    )
                ],
            )

        signals: list[SignalDetail] = []

        # Signal 1: Selector survival rate
        sel_signal = await self._check_selector_survival(
            profile, browser, kb, domain,
        )
        signals.append(sel_signal)

        # Signal 2: AX tree diff
        ax_signal = await self._check_ax_tree(profile, browser)
        signals.append(ax_signal)

        # Signal 3: API schema diff
        api_signal = self._check_api_schema(profile, browser)
        signals.append(api_signal)

        combined = sum(s.weighted_score for s in signals)
        combined = min(1.0, max(0.0, combined))

        if combined >= THRESHOLD_RECON:
            action = "recon"
        elif combined >= THRESHOLD_PATCH:
            action = "patch"
        else:
            action = "none"

        logger.info(
            "ChangeDetector %s: score=%.3f action=%s",
            domain, combined, action,
        )
        return ChangeDetectionResult(
            score=combined, action=action, signal_details=signals,
        )

    async def _check_selector_survival(
        self,
        profile: SiteProfile,
        browser: IBrowser,
        kb: KBManager,
        domain: str,
    ) -> SignalDetail:
        """Test top-N selectors from workflows for survival."""
        selectors = self._collect_selectors(profile, kb, domain)
        if not selectors:
            return SignalDetail(
                name="selector_survival",
                weight=_W_SELECTOR,
                raw_score=0.0,
                weighted_score=0.0,
                detail="No selectors to test.",
            )

        test_set = selectors[: self._top_n]
        dead = 0
        for sel in test_set:
            try:
                elements = await browser.query_selector_all(sel)
                if not elements:
                    dead += 1
            except Exception:
                dead += 1

        raw = dead / len(test_set) if test_set else 0.0
        weighted = raw * _W_SELECTOR
        return SignalDetail(
            name="selector_survival",
            weight=_W_SELECTOR,
            raw_score=raw,
            weighted_score=weighted,
            detail=f"{dead}/{len(test_set)} selectors dead",
        )

    @staticmethod
    def _collect_selectors(
        profile: SiteProfile,
        kb: KBManager,
        domain: str,
    ) -> list[str]:
        """Gather selectors from profile and workflows."""
        selectors: list[str] = []

        # From profile content patterns
        for cp in profile.content_types:
            selectors.extend(cp.key_selectors.values())

        # From navigation
        if profile.navigation.menu_selector:
            selectors.append(profile.navigation.menu_selector)
        if profile.search_functionality and profile.search_functionality.input_selector:
            selectors.append(profile.search_functionality.input_selector)

        # From workflows in KB
        patterns_dir = kb.base_dir / domain / "url_patterns"
        if patterns_dir.exists():
            for p_dir in patterns_dir.iterdir():
                if not p_dir.is_dir():
                    continue
                wf_current = p_dir / "workflows" / "current"
                if not wf_current.exists():
                    continue
                try:
                    target = (
                        p_dir / "workflows" / wf_current.resolve().name
                    )
                    wf = json.loads(target.read_text())
                    for step in wf.get("steps", []):
                        sel = step.get("selector")
                        if sel:
                            selectors.append(sel)
                except Exception:
                    continue

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for s in selectors:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique

    async def _check_ax_tree(
        self,
        profile: SiteProfile,
        browser: IBrowser,
    ) -> SignalDetail:
        """Compare current AX tree hash with stored hash."""
        stored_hash = profile.ax_hash or ""
        try:
            ax_snapshot = await browser.accessibility_snapshot()
            current_hash = _hash_ax_tree(ax_snapshot)
        except Exception as exc:
            logger.warning("AX tree snapshot failed: %s", exc)
            return SignalDetail(
                name="ax_tree_diff",
                weight=_W_AX_TREE,
                raw_score=0.0,
                weighted_score=0.0,
                detail=f"AX snapshot failed: {exc}",
            )

        if not stored_hash:
            # No baseline; treat as minor change
            raw = 0.3
        elif stored_hash == current_hash:
            raw = 0.0
        else:
            raw = 1.0

        weighted = raw * _W_AX_TREE
        return SignalDetail(
            name="ax_tree_diff",
            weight=_W_AX_TREE,
            raw_score=raw,
            weighted_score=weighted,
            detail=(
                f"stored={stored_hash[:8]}.. current={current_hash[:8]}.."
                if stored_hash
                else "No stored AX hash"
            ),
        )

    @staticmethod
    def _check_api_schema(
        profile: SiteProfile,
        browser: IBrowser,
    ) -> SignalDetail:
        """Compare stored API schema fingerprint.

        Full network interception requires a separate HAR capture pass;
        here we compare the stored fingerprint against itself as a
        placeholder. The score is 0 unless endpoints were explicitly
        removed from the profile.
        """
        stored = profile.api_schema_fingerprint
        if not stored:
            return SignalDetail(
                name="api_schema_diff",
                weight=_W_API,
                raw_score=0.0,
                weighted_score=0.0,
                detail="No stored API schema fingerprint.",
            )

        endpoint_count = len(profile.api_endpoints)
        fingerprint_count = len(stored)
        if fingerprint_count == 0:
            raw = 0.0
        elif endpoint_count < fingerprint_count:
            raw = (fingerprint_count - endpoint_count) / fingerprint_count
        else:
            raw = 0.0

        weighted = raw * _W_API
        return SignalDetail(
            name="api_schema_diff",
            weight=_W_API,
            raw_score=raw,
            weighted_score=weighted,
            detail=f"endpoints={endpoint_count}, fingerprints={fingerprint_count}",
        )


def _hash_ax_tree(ax: dict[str, Any]) -> str:
    """Compute a stable hash of an accessibility tree snapshot."""
    canonical = json.dumps(ax, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
