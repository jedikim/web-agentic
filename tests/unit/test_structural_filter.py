"""Unit tests for Stage 1 structural filter — region classification + filtering."""
from __future__ import annotations

from src.core.structural_filter import (
    SemanticRegion,
    StructuralFilter,
    classify_region,
)
from src.core.types import ExtractedElement


def _el(
    eid: str = "el",
    text: str | None = None,
    role: str | None = None,
    bbox: tuple[int, int, int, int] = (0, 300, 100, 40),
    parent_context: str | None = None,
    landmark: str | None = None,
    el_type: str = "button",
) -> ExtractedElement:
    return ExtractedElement(
        eid=eid, type=el_type, text=text, role=role,
        bbox=bbox, visible=True, parent_context=parent_context,
        landmark=landmark,
    )


# ── classify_region ──────────────────────────────────


class TestClassifyRegion:
    """Tests for classify_region()."""

    def test_landmark_nav(self) -> None:
        assert classify_region(_el(landmark="nav")) == SemanticRegion.NAV

    def test_landmark_header(self) -> None:
        assert classify_region(_el(landmark="header")) == SemanticRegion.HEADER

    def test_landmark_footer(self) -> None:
        assert classify_region(_el(landmark="footer")) == SemanticRegion.FOOTER

    def test_landmark_aside(self) -> None:
        assert classify_region(_el(landmark="aside")) == SemanticRegion.SIDEBAR

    def test_landmark_main(self) -> None:
        assert classify_region(_el(landmark="main")) == SemanticRegion.MAIN

    def test_landmark_section(self) -> None:
        assert classify_region(_el(landmark="section")) == SemanticRegion.MAIN

    def test_parent_context_nav(self) -> None:
        assert classify_region(_el(parent_context="site-nav")) == SemanticRegion.NAV

    def test_parent_context_header(self) -> None:
        assert classify_region(_el(parent_context="header-area")) == SemanticRegion.HEADER

    def test_parent_context_modal(self) -> None:
        assert classify_region(_el(parent_context="modal-content")) == SemanticRegion.DIALOG

    def test_role_navigation(self) -> None:
        assert classify_region(_el(role="navigation")) == SemanticRegion.NAV

    def test_role_banner(self) -> None:
        assert classify_region(_el(role="banner")) == SemanticRegion.HEADER

    def test_role_dialog(self) -> None:
        assert classify_region(_el(role="dialog")) == SemanticRegion.DIALOG

    def test_role_contentinfo(self) -> None:
        assert classify_region(_el(role="contentinfo")) == SemanticRegion.FOOTER

    def test_bbox_header_heuristic(self) -> None:
        """Elements near the top (y < 150) should be classified as HEADER."""
        el = _el(bbox=(0, 50, 100, 40))
        assert classify_region(el) == SemanticRegion.HEADER

    def test_bbox_footer_heuristic(self) -> None:
        """Elements near the bottom should be classified as FOOTER."""
        el = _el(bbox=(0, 950, 100, 40))
        assert classify_region(el, viewport_height=1080) == SemanticRegion.FOOTER

    def test_unknown_fallback(self) -> None:
        """Elements with no signals should be UNKNOWN."""
        el = _el(bbox=(0, 500, 100, 40))
        assert classify_region(el) == SemanticRegion.UNKNOWN

    def test_landmark_takes_priority_over_parent(self) -> None:
        """Landmark tag should override parent_context."""
        el = _el(landmark="nav", parent_context="footer-area")
        assert classify_region(el) == SemanticRegion.NAV

    def test_parent_takes_priority_over_role(self) -> None:
        """parent_context should override ARIA role."""
        el = _el(parent_context="header-bar", role="navigation")
        assert classify_region(el) == SemanticRegion.HEADER

    def test_role_takes_priority_over_bbox(self) -> None:
        """ARIA role should override bbox heuristic."""
        el = _el(role="navigation", bbox=(0, 50, 100, 40))
        assert classify_region(el) == SemanticRegion.NAV


# ── StructuralFilter ─────────────────────────────────


class TestStructuralFilter:
    """Tests for StructuralFilter.filter()."""

    def test_passthrough_below_limit(self) -> None:
        """If candidates <= max, return all."""
        sf = StructuralFilter(max_candidates=80)
        candidates = [_el(eid=f"el-{i}") for i in range(10)]
        result = sf.filter(candidates, "search something")
        assert len(result) == 10

    def test_limits_output(self) -> None:
        """Should not return more than max_candidates."""
        sf = StructuralFilter(max_candidates=5)
        candidates = [_el(eid=f"el-{i}", bbox=(0, 300, 100, 40)) for i in range(20)]
        result = sf.filter(candidates, "click something")
        assert len(result) == 5

    def test_search_intent_prefers_header(self) -> None:
        """'search' intent should prefer header-region elements."""
        sf = StructuralFilter(max_candidates=3)
        candidates = [
            _el(eid="header-search", text="Search", landmark="header"),
            _el(eid="footer-link", text="Privacy", landmark="footer"),
            _el(eid="main-btn", text="Buy", landmark="main"),
            _el(eid="nav-search", text="Search bar", landmark="nav"),
            _el(eid="random1", text="Other", bbox=(0, 500, 100, 40)),
            _el(eid="random2", text="Other2", bbox=(0, 600, 100, 40)),
        ]
        result = sf.filter(candidates, "search for products")
        eids = [el.eid for el in result]
        # Header and nav elements should come first for search intent
        assert eids[0] in ("header-search", "nav-search")

    def test_login_intent_prefers_header_dialog(self) -> None:
        """'login' intent should prefer header/dialog elements."""
        sf = StructuralFilter(max_candidates=3)
        candidates = [
            _el(eid="footer-link", text="Terms", landmark="footer"),
            _el(eid="dialog-login", text="Sign In", role="dialog"),
            _el(eid="main-text", text="Welcome", landmark="main"),
            _el(eid="header-login", text="로그인", landmark="header"),
            _el(eid="random", text="Random", bbox=(0, 500, 100, 40)),
            _el(eid="random2", text="Random2", bbox=(0, 600, 100, 40)),
        ]
        result = sf.filter(candidates, "로그인")
        eids = [el.eid for el in result]
        assert "header-login" in eids[:3]

    def test_footer_intent_prefers_footer(self) -> None:
        """'privacy' intent should prefer footer elements."""
        sf = StructuralFilter(max_candidates=2)
        candidates = [
            _el(eid="header-logo", text="Logo", landmark="header"),
            _el(eid="footer-privacy", text="Privacy Policy", landmark="footer"),
            _el(eid="main-content", text="Content", landmark="main"),
            _el(eid="random", text="random", bbox=(0, 500, 100, 40)),
        ]
        result = sf.filter(candidates, "click privacy policy")
        assert result[0].eid == "footer-privacy"

    def test_keyword_scoring_within_region(self) -> None:
        """Within a preferred region, keyword-matched elements rank higher."""
        sf = StructuralFilter(max_candidates=2)
        candidates = [
            _el(eid="nav-about", text="About Us", landmark="nav"),
            _el(eid="nav-menu", text="메뉴 Menu", landmark="nav"),
            _el(eid="main-product", text="Product", landmark="main"),
            _el(eid="main-other", text="Other content", landmark="main"),
        ]
        result = sf.filter(candidates, "navigate to menu")
        # nav-menu should rank first due to keyword match + nav region
        assert result[0].eid == "nav-menu"

    def test_no_intent_match_uses_keyword_fallback(self) -> None:
        """When intent doesn't match any region pattern, keyword score still works."""
        sf = StructuralFilter(max_candidates=3)
        candidates = [
            _el(eid="el-a", text="Download report"),
            _el(eid="el-b", text="Upload file"),
            _el(eid="el-c", text="Download data export"),
            _el(eid="el-d", text="Cancel"),
            _el(eid="el-e", text="Settings"),
            _el(eid="el-f", text="Help"),
        ]
        result = sf.filter(candidates, "download the report")
        # Elements with "download" should rank higher
        texts = [(el.text or "") for el in result[:2]]
        assert any("Download" in t for t in texts)

    def test_deduplication(self) -> None:
        """Elements should not appear twice even if in preferred region."""
        sf = StructuralFilter(max_candidates=5)
        el_nav = _el(eid="nav-search", text="Search", landmark="nav")
        candidates = [el_nav] + [
            _el(eid=f"el-{i}", bbox=(0, 500, 100, 40)) for i in range(10)
        ]
        result = sf.filter(candidates, "search for item")
        eids = [el.eid for el in result]
        assert eids.count("nav-search") == 1

    def test_product_intent_prefers_main(self) -> None:
        """Product-related intent should prefer main region."""
        sf = StructuralFilter(max_candidates=3)
        candidates = [
            _el(eid="header-logo", text="Logo", landmark="header"),
            _el(eid="nav-link", text="Home", landmark="nav"),
            _el(eid="main-product", text="상품 목록", landmark="main"),
            _el(eid="sidebar-filter", text="Filter", landmark="aside"),
            _el(eid="random", text="Other", bbox=(0, 500, 100, 40)),
            _el(eid="random2", text="Other2", bbox=(0, 600, 100, 40)),
        ]
        result = sf.filter(candidates, "가장 싼 상품 클릭")
        assert result[0].eid == "main-product"

    def test_dialog_intent_prefers_dialog(self) -> None:
        """Popup/close intent should prefer dialog elements."""
        sf = StructuralFilter(max_candidates=2)
        candidates = [
            _el(eid="main-btn", text="Submit", landmark="main"),
            _el(eid="dialog-close", text="닫기", role="dialog"),
            _el(eid="header-btn", text="Menu", landmark="header"),
            _el(eid="other", text="Link", bbox=(0, 500, 100, 40)),
        ]
        result = sf.filter(candidates, "팝업 닫기")
        assert result[0].eid == "dialog-close"
