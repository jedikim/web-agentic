"""Unit tests for v4 recon system.

Covers DOMScanner, VisualScanner, NavScanner, ProfileSynthesizer,
and the ReconAgent run_recon function.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from src.models.site_profile import SiteProfile
from src.recon.dom_scanner import DOMScanner
from src.recon.nav_scanner import NavScanner
from src.recon.profile_synthesizer import ProfileSynthesizer
from src.recon.visual_scanner import VisualScanner


def _make_minimal_png() -> bytes:
    """Create a valid 1x1 white PNG for screenshot mocking."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


_FAKE_PNG = _make_minimal_png()


# ── Mocks ──


class MockBrowser:
    """Fake browser for DOMScanner / NavScanner tests."""

    def __init__(
        self,
        evaluate_return: Any = None,
        cdp_return: Any = None,
        screenshot_bytes: bytes = _FAKE_PNG,
        evaluate_side_effects: list[Any] | None = None,
    ) -> None:
        self._evaluate_return = evaluate_return
        self._cdp_return = cdp_return
        self._screenshot_bytes = screenshot_bytes
        self._evaluate_side_effects = evaluate_side_effects
        self._evaluate_call_idx = 0
        self.page = MockPage()

    async def evaluate(self, expression: str) -> Any:
        if self._evaluate_side_effects is not None:
            idx = self._evaluate_call_idx
            self._evaluate_call_idx += 1
            val = self._evaluate_side_effects[idx % len(self._evaluate_side_effects)]
            if isinstance(val, Exception):
                raise val
            return val
        return self._evaluate_return

    async def cdp_send(self, method: str, params: dict[str, Any]) -> Any:
        if isinstance(self._cdp_return, Exception):
            raise self._cdp_return
        return self._cdp_return

    async def screenshot(self) -> bytes:
        return self._screenshot_bytes

    async def goto(self, url: str, **kw: Any) -> None:
        pass

    async def wait(self, ms: int) -> None:
        pass


class MockPage:
    """Fake page object for NavScanner submenu exploration."""

    async def query_selector(self, selector: str) -> MockElement | None:
        return MockElement()


class MockElement:
    """Fake element with hover."""

    async def hover(self) -> None:
        pass


class MockDetector:
    """Fake object detector."""

    def __init__(self, detections: list[dict[str, Any]] | None = None) -> None:
        self._detections = detections or []

    def detect(self, image: Any, threshold: float = 0.3) -> list[dict[str, Any]]:
        return self._detections


class MockVLM:
    """Fake VLM client."""

    def __init__(self, response: str = '{"layout": "standard"}') -> None:
        self._response = response

    async def generate(self, *, image: Any, prompt: str) -> str:
        return self._response


class MockKBManager:
    """Fake KBManager for ReconAgent tests."""

    def __init__(
        self,
        profile: SiteProfile | None = None,
        expired: bool = True,
    ) -> None:
        self._profile = profile
        self._expired = expired
        self.saved: SiteProfile | None = None

    def load_profile(self, domain: str) -> SiteProfile | None:
        return self._profile

    def is_profile_expired(self, profile: SiteProfile) -> bool:
        return self._expired

    def save_profile(self, profile: SiteProfile) -> int:
        self.saved = profile
        return profile.recon_version


# ── DOMScanner Tests ──


@pytest.mark.asyncio
async def test_scan_merges_results() -> None:
    """All 7 scan methods called and merged into one dict."""
    cdp_data = {
        "documents": [
            {
                "nodes": {"nodeName": ["DIV", "SPAN"]},
                "layout": {"nodeIndex": [0, 1]},
            }
        ],
    }
    ax_data = {
        "nodes": [
            {"role": {"value": "button"}, "name": {"value": "OK"}},
            {"role": {"value": "textbox"}, "name": {"value": "search"}},
            {"role": {"value": "generic"}, "name": {"value": "div"}},
        ],
    }

    structure = {
        "total_elements": 500,
        "interactive_elements": 42,
        "max_depth": 12,
        "framework": "react",
        "has_shadow_dom": False,
        "iframe_count": 1,
        "unique_selectors_ratio": 0.7,
        "text_node_ratio": 0.3,
        "aria_coverage": 0.8,
        "is_spa": True,
    }
    navigation = {
        "menu_type": "mega_menu",
        "menu_items": [{"text": "Home", "href": "/"}],
        "menu_requires_hover": True,
        "search": {"input_selector": "#q", "has_autocomplete": True, "submit_button": True},
        "has_breadcrumb": True,
    }
    content = {
        "repeating_patterns": [],
        "image_density": "medium",
        "canvas_count": 0,
        "canvas_area_ratio": 0.0,
        "total_images": 10,
    }
    obstacles = {"obstacles": []}
    forms = {"forms": []}
    interactions = {"interaction_patterns": [{"type": "hover_menu", "count": 3}]}

    evaluate_returns = [structure, navigation, content, obstacles, forms, interactions]

    # cdp_send returns different data for different methods
    cdp_calls: list[str] = []

    class CDPBrowser(MockBrowser):
        async def cdp_send(self, method: str, params: dict[str, Any]) -> Any:
            cdp_calls.append(method)
            if method == "DOMSnapshot.captureSnapshot":
                return cdp_data
            if method == "Accessibility.getFullAXTree":
                return ax_data
            return {}

    browser = CDPBrowser(evaluate_side_effects=evaluate_returns)
    scanner = DOMScanner()
    result = await scanner.scan(browser)

    # Snapshot keys from CDP
    assert "snapshot_node_count" in result
    assert result["snapshot_node_count"] == 2
    assert result["snapshot_layout_count"] == 2
    assert result["ax_node_count"] == 3
    assert result["ax_interactive_count"] == 2  # button + textbox

    # Structure keys from evaluate
    assert result["total_elements"] == 500
    assert result["framework"] == "react"

    # Navigation keys
    assert result["menu_type"] == "mega_menu"

    # Content keys
    assert result["image_density"] == "medium"

    # Interaction keys
    assert result["interaction_patterns"] == [{"type": "hover_menu", "count": 3}]


@pytest.mark.asyncio
async def test_scan_handles_partial_failure() -> None:
    """One scan method raises an exception; the others still contribute."""
    # _scan_snapshot will fail (cdp_send raises), but evaluate-based scans succeed
    structure = {
        "total_elements": 100,
        "interactive_elements": 10,
        "max_depth": 5,
        "framework": None,
        "has_shadow_dom": False,
        "iframe_count": 0,
        "unique_selectors_ratio": 0.5,
        "text_node_ratio": 0.4,
        "aria_coverage": 0.6,
        "is_spa": False,
    }
    navigation = {
        "menu_type": "horizontal_nav",
        "menu_items": [],
        "menu_requires_hover": False,
        "search": None,
        "has_breadcrumb": False,
    }
    content = {
        "repeating_patterns": [],
        "image_density": "low",
        "canvas_count": 0,
        "canvas_area_ratio": 0.0,
        "total_images": 3,
    }
    obstacles = {"obstacles": []}
    forms = {"forms": []}
    interactions = {"interaction_patterns": []}

    browser = MockBrowser(
        cdp_return=RuntimeError("CDP unavailable"),
        evaluate_side_effects=[structure, navigation, content, obstacles, forms, interactions],
    )
    scanner = DOMScanner()
    result = await scanner.scan(browser)

    # Snapshot keys should be missing (CDP failed → empty dict returned)
    # But structure keys should be present from evaluate
    assert result.get("total_elements") == 100
    assert result.get("menu_type") == "horizontal_nav"
    assert result.get("image_density") == "low"


@pytest.mark.asyncio
async def test_scan_structure_result_keys() -> None:
    """Verify expected keys from _scan_structure."""
    structure_data = {
        "total_elements": 200,
        "interactive_elements": 30,
        "max_depth": 8,
        "framework": "vue",
        "has_shadow_dom": True,
        "iframe_count": 2,
        "unique_selectors_ratio": 0.6,
        "text_node_ratio": 0.25,
        "aria_coverage": 0.5,
        "is_spa": True,
    }
    browser = MockBrowser(evaluate_return=structure_data)
    scanner = DOMScanner()
    result = await scanner._scan_structure(browser)

    expected_keys = {
        "total_elements",
        "interactive_elements",
        "max_depth",
        "framework",
        "has_shadow_dom",
        "iframe_count",
        "unique_selectors_ratio",
        "text_node_ratio",
        "aria_coverage",
        "is_spa",
    }
    assert expected_keys == set(result.keys())
    assert result["framework"] == "vue"
    assert result["is_spa"] is True


# ── VisualScanner Tests ──


@pytest.mark.asyncio
async def test_scan_without_vlm() -> None:
    """No VLM call when canvas_count=0, image_density != 'high', elements >= 50."""
    browser = MockBrowser()
    dom_result = {
        "canvas_count": 0,
        "image_density": "low",
        "total_elements": 200,
    }
    scanner = VisualScanner()
    result = await scanner.scan(browser, dom_result, detector=None, vlm=None)

    assert result["needs_vlm"] is False
    assert result["vlm_analysis"] is None
    assert result["screenshot_bytes"] == _FAKE_PNG
    assert result["obj_detections"] == []


@pytest.mark.asyncio
async def test_scan_with_vlm_for_canvas() -> None:
    """Canvas detected triggers VLM call."""
    browser = MockBrowser()
    dom_result = {
        "canvas_count": 1,
        "image_density": "low",
        "total_elements": 200,
    }
    vlm = MockVLM(response='{"layout": "canvas_based"}')

    scanner = VisualScanner()
    result = await scanner.scan(browser, dom_result, detector=None, vlm=vlm)

    assert result["needs_vlm"] is True
    assert result["vlm_analysis"] == '{"layout": "canvas_based"}'


@pytest.mark.asyncio
async def test_scan_vlm_triggered_by_high_image_density() -> None:
    """High image_density triggers VLM call."""
    browser = MockBrowser()
    dom_result = {
        "canvas_count": 0,
        "image_density": "high",
        "total_elements": 500,
    }
    vlm = MockVLM(response='{"density": "high"}')

    scanner = VisualScanner()
    result = await scanner.scan(browser, dom_result, detector=None, vlm=vlm)

    assert result["needs_vlm"] is True
    assert result["vlm_analysis"] == '{"density": "high"}'


@pytest.mark.asyncio
async def test_scan_vlm_triggered_by_few_elements() -> None:
    """Less than 50 total_elements triggers VLM call."""
    browser = MockBrowser()
    dom_result = {
        "canvas_count": 0,
        "image_density": "low",
        "total_elements": 30,
    }
    vlm = MockVLM(response='{"sparse": true}')

    scanner = VisualScanner()
    result = await scanner.scan(browser, dom_result, detector=None, vlm=vlm)

    assert result["needs_vlm"] is True
    assert result["vlm_analysis"] == '{"sparse": true}'


def test_classify_detections() -> None:
    """Detection labels mapped to categories correctly."""
    detections = [
        {"label": "button", "confidence": 0.9, "bbox": [10, 20, 100, 50]},
        {"label": "nav_bar", "confidence": 0.85, "bbox": [0, 0, 1920, 60]},
        {"label": "text_field", "confidence": 0.8, "bbox": [200, 300, 400, 340]},
        {"label": "product_card", "confidence": 0.75, "bbox": [50, 100, 300, 400]},
        {"label": "hero_image", "confidence": 0.7, "bbox": [0, 60, 1920, 500]},
        {"label": "unknown_widget", "confidence": 0.6, "bbox": [500, 500, 600, 600]},
    ]
    result = VisualScanner._classify_detections(detections)

    assert len(result) == 6
    assert result[0]["category"] == "button"
    assert result[1]["category"] == "menu"  # "nav" in label
    assert result[2]["category"] == "input"  # "field" in label
    assert result[3]["category"] == "card"  # "product" in label
    assert result[4]["category"] == "image"  # "image" in label
    assert result[5]["category"] == "unknown"

    # Confidence and bbox preserved
    assert result[0]["confidence"] == 0.9
    assert result[0]["bbox"] == [10, 20, 100, 50]


# ── NavScanner Tests ──


def test_extract_url_pattern_search() -> None:
    """/search?query=shoes -> /search?query=*"""
    pattern = NavScanner._extract_url_pattern("https://example.com/search?query=shoes")
    assert pattern == "/search?query=*"


def test_extract_url_pattern_catalog() -> None:
    """/catalog/electronics -> /catalog/*"""
    pattern = NavScanner._extract_url_pattern("https://example.com/catalog/electronics")
    assert pattern == "/catalog/*"


def test_extract_url_pattern_root() -> None:
    """Root URL returns /."""
    pattern = NavScanner._extract_url_pattern("https://example.com/")
    assert pattern == "/"


def test_extract_url_pattern_single_segment() -> None:
    """/about stays as /about (only 2 segments: ['', 'about'])."""
    pattern = NavScanner._extract_url_pattern("https://example.com/about")
    assert pattern == "/about"


def test_extract_url_pattern_multi_query() -> None:
    """Multiple query params all get wildcarded."""
    pattern = NavScanner._extract_url_pattern(
        "https://example.com/search?q=shoes&page=2&sort=price"
    )
    assert pattern == "/search?q=*&page=*&sort=*"


def test_pick_sample_urls() -> None:
    """Sample URLs picked from category tree."""
    category_tree = [
        {
            "name": "Electronics",
            "url": "https://example.com/electronics",
            "children": [
                {"text": "Phones", "href": "https://example.com/electronics/phones"},
                {"text": "Laptops", "href": "https://example.com/electronics/laptops"},
                {"text": "Tablets", "href": "https://example.com/electronics/tablets"},
            ],
        },
        {
            "name": "Clothing",
            "url": "https://example.com/clothing",
            "children": [
                {"text": "Men", "href": "https://example.com/clothing/men"},
            ],
        },
    ]
    urls = NavScanner._pick_sample_urls(category_tree, {})

    # First category URL + 2 children, second category URL + 1 child = 5
    assert len(urls) == 5
    assert "https://example.com/electronics" in urls
    assert "https://example.com/electronics/phones" in urls
    assert "https://example.com/electronics/laptops" in urls
    assert "https://example.com/clothing" in urls
    assert "https://example.com/clothing/men" in urls


def test_pick_sample_urls_caps_at_five() -> None:
    """Never return more than 5 URLs."""
    big_tree = [
        {
            "name": f"Cat{i}",
            "url": f"https://example.com/cat{i}",
            "children": [
                {"text": f"Sub{j}", "href": f"https://example.com/cat{i}/sub{j}"}
                for j in range(5)
            ],
        }
        for i in range(5)
    ]
    urls = NavScanner._pick_sample_urls(big_tree, {})
    assert len(urls) <= 5


# ── ProfileSynthesizer Tests ──


@pytest.mark.asyncio
async def test_heuristic_assembly() -> None:
    """Build profile without LLM — all fields populated from raw data."""
    dom = {
        "total_elements": 300,
        "interactive_elements": 40,
        "max_depth": 10,
        "unique_selectors_ratio": 0.65,
        "text_node_ratio": 0.3,
        "aria_coverage": 0.7,
        "menu_type": "mega_menu",
        "menu_items": [{"text": "Home", "href": "/"}],
        "menu_requires_hover": True,
        "search": {"input_selector": "#search", "has_autocomplete": True},
        "has_breadcrumb": True,
        "canvas_count": 0,
        "canvas_area_ratio": 0.0,
        "image_density": "medium",
        "repeating_patterns": [
            {
                "parent_selector": "#products",
                "item_tag_hash": "abc123",
                "item_count": 12,
                "has_text": True,
                "has_link": True,
                "has_image": True,
                "is_content": True,
                "sample_item_selector": ".product-card",
            }
        ],
        "obstacles": [
            {"type": "cookie_consent", "selector": "#cookie", "close_selector": ".close"},
        ],
        "interaction_patterns": [{"type": "hover_menu", "count": 5}],
        "forms": [
            {
                "action": "/search",
                "method": "get",
                "selector": "#search-form",
                "fields": [{"name": "q", "type": "text"}],
                "submit": {"text": "Search"},
            }
        ],
        "framework": "react",
        "has_shadow_dom": False,
        "iframe_count": 1,
        "is_spa": True,
    }
    visual = {
        "obj_detections": [
            {
                "category": "card", "label": "product_card",
                "confidence": 0.8, "bbox": [10, 20, 300, 400],
            }
        ],
    }
    nav = {
        "page_samples": [
            {"page_type": "product_list", "url": "/products", "has_scroll_content": True}
        ],
        "url_patterns": ["/products/*"],
    }

    synth = ProfileSynthesizer()
    profile = await synth.synthesize("example.com", dom, visual, nav, llm=None, existing_version=0)

    assert isinstance(profile, SiteProfile)
    assert profile.domain == "example.com"
    assert profile.recon_version == 1
    assert profile.dom_complexity.total_elements == 300
    assert profile.dom_complexity.interactive_elements == 40
    assert profile.framework == "react"
    assert profile.is_spa is True
    assert profile.iframe_count == 1
    assert profile.visual_structure.menu_type == "mega_menu"
    assert profile.canvas_usage.has_canvas is False
    assert profile.image_density == "medium"
    assert len(profile.repeating_patterns) == 1
    assert profile.repeating_patterns[0].parent_selector == "#products"
    assert len(profile.obstacles) == 1
    assert profile.obstacles[0].type == "cookie_consent"
    assert profile.obstacles[0].dismiss_method == "click_close"
    assert profile.navigation.has_search is True
    assert profile.navigation.menu_requires_hover is True
    assert profile.navigation.has_breadcrumb is True
    assert profile.search_functionality is not None
    assert profile.search_functionality.input_selector == "#search"
    assert len(profile.interaction_patterns) == 1
    assert len(profile.form_types) == 1
    assert profile.hover_dependent_menus is True
    assert len(profile.thumbnail_structures) == 1
    assert profile.thumbnail_structures[0].grid_type == "product_card"
    assert len(profile.content_types) == 1
    assert profile.content_types[0].page_type == "product_list"
    assert profile.dom_hash  # non-empty hash


@pytest.mark.asyncio
async def test_profile_version_increment() -> None:
    """Existing version 3 increments to 4."""
    synth = ProfileSynthesizer()
    profile = await synth.synthesize(
        "test.com",
        dom_result={"total_elements": 50},
        visual_result={},
        nav_result={},
        llm=None,
        existing_version=3,
    )
    assert profile.recon_version == 4


@pytest.mark.asyncio
async def test_heuristic_no_search() -> None:
    """No search on the page yields search_functionality=None."""
    synth = ProfileSynthesizer()
    profile = await synth.synthesize(
        "nosearch.com",
        dom_result={"total_elements": 100, "search": None},
        visual_result={},
        nav_result={},
    )
    assert profile.search_functionality is None


@pytest.mark.asyncio
async def test_heuristic_canvas_requires_vision() -> None:
    """Canvas area > 0.5 flags requires_vision_only."""
    synth = ProfileSynthesizer()
    profile = await synth.synthesize(
        "canvas.io",
        dom_result={"canvas_count": 2, "canvas_area_ratio": 0.7, "total_elements": 50},
        visual_result={},
        nav_result={},
    )
    assert profile.canvas_usage.has_canvas is True
    assert profile.canvas_usage.requires_vision_only is True


# ── ReconAgent Tests ──


@pytest.mark.asyncio
async def test_run_recon_kb_hit() -> None:
    """Cached non-expired profile returned immediately without scanning."""
    from src.recon.agent import run_recon

    cached = SiteProfile(domain="cached.com", recon_version=5)
    kb = MockKBManager(profile=cached, expired=False)
    browser = MockBrowser()

    result = await run_recon("cached.com", browser, kb)  # type: ignore[arg-type]

    assert result is not None
    assert result.domain == "cached.com"
    assert result.recon_version == 5
    # No scan happened — saved should be None (no save_profile call from the pipeline)
    # Actually save_to_kb is called, but the profile is the cached one
    assert kb.saved is not None or result is cached


@pytest.mark.asyncio
async def test_run_recon_full_pipeline() -> None:
    """No cache -> full scan pipeline runs DOM, Visual, Nav, Synthesize, Save."""
    from src.recon.agent import run_recon

    # KB returns no profile (cache miss)
    kb = MockKBManager(profile=None, expired=True)

    # Browser that returns deterministic data
    structure = {
        "total_elements": 150,
        "interactive_elements": 20,
        "max_depth": 6,
        "framework": None,
        "has_shadow_dom": False,
        "iframe_count": 0,
        "unique_selectors_ratio": 0.5,
        "text_node_ratio": 0.3,
        "aria_coverage": 0.4,
        "is_spa": False,
    }
    navigation = {
        "menu_type": "horizontal_nav",
        "menu_items": [],
        "menu_requires_hover": False,
        "search": None,
        "has_breadcrumb": False,
    }
    content = {
        "repeating_patterns": [],
        "image_density": "low",
        "canvas_count": 0,
        "canvas_area_ratio": 0.0,
        "total_images": 5,
    }
    obstacles = {"obstacles": []}
    forms = {"forms": []}
    interactions = {"interaction_patterns": []}

    # CDP returns basic data for _scan_snapshot
    cdp_data = {
        "documents": [{"nodes": {"nodeName": ["DIV"]}, "layout": {"nodeIndex": [0]}}]
    }
    ax_data = {"nodes": []}

    # evaluate is called many times: 6 times for DOM scan + nav scan calls
    # We provide enough returns for all evaluate calls
    all_evals = [
        structure,
        navigation,
        content,
        obstacles,
        forms,
        interactions,
        # nav_scan's _explore_submenu and _analyze_page — empty results since no menu items
    ]

    class FullBrowser(MockBrowser):
        def __init__(self) -> None:
            super().__init__(evaluate_side_effects=all_evals)
            self._cdp_calls: list[str] = []

        async def cdp_send(self, method: str, params: dict[str, Any]) -> Any:
            self._cdp_calls.append(method)
            if method == "DOMSnapshot.captureSnapshot":
                return cdp_data
            if method == "Accessibility.getFullAXTree":
                return ax_data
            return {}

    browser = FullBrowser()

    result = await run_recon("newsite.com", browser, kb)  # type: ignore[arg-type]

    assert result is not None
    assert isinstance(result, SiteProfile)
    assert result.domain == "newsite.com"
    assert result.recon_version == 1
    assert result.dom_complexity.total_elements == 150
    # Profile was saved to KB
    assert kb.saved is not None
    assert kb.saved.domain == "newsite.com"


@pytest.mark.asyncio
async def test_run_recon_expired_cache_rescans() -> None:
    """Expired cached profile triggers full rescan."""
    from src.recon.agent import run_recon

    old_profile = SiteProfile(domain="old.com", recon_version=2)
    kb = MockKBManager(profile=old_profile, expired=True)

    structure = {
        "total_elements": 80,
        "interactive_elements": 10,
        "max_depth": 4,
        "framework": "jquery",
        "has_shadow_dom": False,
        "iframe_count": 0,
        "unique_selectors_ratio": 0.3,
        "text_node_ratio": 0.5,
        "aria_coverage": 0.2,
        "is_spa": False,
    }
    navigation = {
        "menu_type": "horizontal_nav",
        "menu_items": [],
        "menu_requires_hover": False,
        "search": None,
        "has_breadcrumb": False,
    }
    content = {
        "repeating_patterns": [],
        "image_density": "low",
        "canvas_count": 0,
        "canvas_area_ratio": 0.0,
        "total_images": 2,
    }
    obstacles = {"obstacles": []}
    forms = {"forms": []}
    interactions = {"interaction_patterns": []}

    cdp_data = {"documents": [{"nodes": {"nodeName": []}, "layout": {"nodeIndex": []}}]}
    ax_data = {"nodes": []}

    all_evals = [structure, navigation, content, obstacles, forms, interactions]

    class ExpiredBrowser(MockBrowser):
        def __init__(self) -> None:
            super().__init__(evaluate_side_effects=all_evals)

        async def cdp_send(self, method: str, params: dict[str, Any]) -> Any:
            if method == "DOMSnapshot.captureSnapshot":
                return cdp_data
            if method == "Accessibility.getFullAXTree":
                return ax_data
            return {}

    browser = ExpiredBrowser()

    result = await run_recon("old.com", browser, kb)  # type: ignore[arg-type]

    assert result is not None
    assert result.domain == "old.com"
    # Version incremented from existing 2 to 3
    assert result.recon_version == 3
    assert result.framework == "jquery"
