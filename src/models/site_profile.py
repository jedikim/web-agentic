"""SiteProfile and sub-dataclasses — site reconnaissance output.

One SiteProfile per domain, stored in Knowledge Base.
Covers 8 categories: meta, DOM, visual, content, obstacles,
navigation, interaction, technology.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ── 2. DOM 구조 ──


@dataclass
class DOMComplexity:
    """DOM structure complexity metrics."""

    total_elements: int = 0
    interactive_elements: int = 0
    max_depth: int = 0
    unique_selectors_ratio: float = 0.0  # 0~1
    text_node_ratio: float = 0.0
    aria_coverage: float = 0.0


# ── 3. 시각 구조 ──


@dataclass
class VisualStructure:
    """Visual layout information."""

    layout_type: str = "responsive"  # "fixed" | "fluid" | "responsive"
    breakpoints: list[int] = field(default_factory=list)
    menu_type: str = "horizontal_nav"
    header_height_px: int = 0
    has_sticky_header: bool = False
    has_footer_nav: bool = False
    color_scheme: str = "light"  # "light" | "dark" | "auto"


@dataclass
class CanvasUsage:
    """Canvas element analysis."""

    has_canvas: bool = False
    canvas_count: int = 0
    canvas_area_ratio: float = 0.0
    canvas_purpose: list[str] = field(default_factory=list)
    requires_vision_only: bool = False


@dataclass
class ThumbnailGrid:
    """Thumbnail/card grid structure on a page."""

    page_url_pattern: str = ""
    grid_type: str = "product_card"
    columns: int = 4
    rows_visible: int = 3
    card_has_text: bool = True
    card_has_price: bool = False
    card_selector: str | None = None
    image_selector: str | None = None


# ── 4. 콘텐츠 패턴 ──


@dataclass
class ContentPattern:
    """Per-page content pattern."""

    page_type: str = "other"  # "home" | "category" | "product_detail" | ...
    url_pattern: str = ""
    dom_readable: bool = True
    requires_scroll: bool = False
    dynamic_content: bool = False
    key_selectors: dict[str, str] = field(default_factory=dict)


@dataclass
class RepeatingPattern:
    """Whitelist-based content recognition.

    Same-structure sibling nodes under a common parent (>=3 repeats)
    with text+link or text+image → confirmed as core content.
    """

    parent_selector: str = ""
    item_tag_hash: str = ""
    item_count: int = 0
    has_text: bool = False
    has_link: bool = False
    has_image: bool = False
    is_content: bool = False
    sample_item_selector: str = ""
    url_pattern: str = ""


@dataclass
class ListStructure:
    """List/grid structure on a page."""

    url_pattern: str = ""
    item_selector: str = ""
    item_count_per_page: int = 0
    has_text_info: bool = True
    has_image_only: bool = False
    sort_options: list[str] = field(default_factory=list)
    filter_selectors: dict[str, str] = field(default_factory=dict)


# ── 5. 장애물 ──


@dataclass
class ObstaclePattern:
    """Interaction-blocking obstacle (popup, cookie consent, etc.)."""

    type: str = "popup"  # "popup" | "cookie_consent" | "login_wall" | ...
    trigger: str = "page_load"
    selector: str | None = None
    close_xy: tuple[float, float] | None = None
    dismiss_method: str = "click_close"
    frequency: str = "once"  # "once" | "every_visit" | "every_page" | "random"


@dataclass
class DismissStrategy:
    """Strategy to dismiss an obstacle."""

    obstacle_type: str = ""
    code: str = ""
    success_rate: float = 0.0


# ── 6. 네비게이션 ──


@dataclass
class NavigationStructure:
    """Site navigation structure."""

    menu_depth: int = 1
    menu_items: list[dict[str, Any]] = field(default_factory=list)
    menu_selector: str = ""
    menu_requires_hover: bool = False
    menu_requires_click: bool = False
    has_search: bool = False
    has_breadcrumb: bool = False


@dataclass
class SearchConfig:
    """Search functionality configuration."""

    input_selector: str = ""
    submit_method: str = "enter"  # "enter" | "button_click" | "auto_suggest"
    submit_selector: str | None = None
    autocomplete: bool = False
    autocomplete_selector: str | None = None
    result_page_pattern: str = ""
    result_item_selector: str | None = None


@dataclass
class CategoryNode:
    """Category tree node."""

    name: str = ""
    url: str | None = None
    selector: str | None = None
    children: list[CategoryNode] = field(default_factory=list)
    depth: int = 0


# ── 7. 인터랙션 패턴 ──


@dataclass
class InteractionPattern:
    """Detected interaction pattern (hover, drag, scroll, etc.)."""

    type: str = ""  # "hover_menu" | "drag_slider" | "infinite_scroll" | ...
    selector: str = ""
    description: str = ""
    recommended_action_type: str = ""
    code_snippet: str | None = None


@dataclass
class FormPattern:
    """Form structure on a page."""

    url_pattern: str = ""
    form_selector: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)
    submit_selector: str = ""
    submit_method: str = "click"  # "click" | "enter" | "ajax"


# ── 8. 기술 특성 ──


@dataclass
class APIEndpoint:
    """Observed API endpoint."""

    url_pattern: str = ""
    method: str = "GET"
    purpose: str = ""  # "search" | "filter" | "pagination" | "auth"
    requires_auth: bool = False
    response_type: str = "json"


# ── SiteProfile (top-level) ──


@dataclass
class SiteProfile:
    """Full site reconnaissance result. Stored once per domain in KB."""

    # 1. 사이트 메타
    domain: str = ""
    purpose: str = ""  # "ecommerce" | "news" | "portal" | "community" | "saas"
    language: str = "en"
    region: str = "US"
    robots_txt: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_recon_at: datetime = field(default_factory=datetime.now)
    recon_version: int = 1
    dom_hash: str = ""
    ax_hash: str | None = None

    # 2. DOM 구조
    dom_complexity: DOMComplexity = field(default_factory=DOMComplexity)
    framework: str | None = None
    has_shadow_dom: bool = False
    iframe_count: int = 0
    iframe_purposes: list[str] = field(default_factory=list)
    is_spa: bool = False
    url_pattern: str = ""

    # 3. 시각 구조
    visual_structure: VisualStructure = field(default_factory=VisualStructure)
    canvas_usage: CanvasUsage = field(default_factory=CanvasUsage)
    image_density: str = "low"  # "low" | "medium" | "high"
    thumbnail_structures: list[ThumbnailGrid] = field(default_factory=list)

    # 4. 콘텐츠 패턴
    content_types: list[ContentPattern] = field(default_factory=list)
    repeating_patterns: list[RepeatingPattern] = field(default_factory=list)
    list_structures: list[ListStructure] = field(default_factory=list)
    pagination_types: list[str] = field(default_factory=list)

    # 5. 장애물
    obstacles: list[ObstaclePattern] = field(default_factory=list)
    obstacle_frequency: str = "none"
    obstacle_dismiss_strategies: list[DismissStrategy] = field(
        default_factory=list,
    )

    # 6. 네비게이션
    navigation: NavigationStructure = field(default_factory=NavigationStructure)
    search_functionality: SearchConfig | None = None
    category_tree: list[CategoryNode] = field(default_factory=list)
    breadcrumb_pattern: str | None = None

    # 7. 인터랙션 패턴
    interaction_patterns: list[InteractionPattern] = field(default_factory=list)
    form_types: list[FormPattern] = field(default_factory=list)
    hover_dependent_menus: bool = False
    drag_interactions: list[str] = field(default_factory=list)
    keyboard_shortcuts: list[str] = field(default_factory=list)
    dynamic_loading: list[str] = field(default_factory=list)

    # 8. 기술 특성
    api_endpoints: list[APIEndpoint] = field(default_factory=list)
    api_schema_fingerprint: dict[str, str] = field(default_factory=dict)
    websocket_usage: bool = False
    auth_flow: str | None = None
    cdn_providers: list[str] = field(default_factory=list)
    csp_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        from dataclasses import asdict

        d = asdict(self)
        # datetime → ISO string
        d["created_at"] = self.created_at.isoformat()
        d["last_recon_at"] = self.last_recon_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteProfile:
        """Deserialize from dict (JSON-parsed)."""
        d = dict(data)
        for key in ("created_at", "last_recon_at"):
            if isinstance(d.get(key), str):
                d[key] = datetime.fromisoformat(d[key])

        # Nested dataclasses
        if isinstance(d.get("dom_complexity"), dict):
            d["dom_complexity"] = DOMComplexity(**d["dom_complexity"])
        if isinstance(d.get("visual_structure"), dict):
            d["visual_structure"] = VisualStructure(**d["visual_structure"])
        if isinstance(d.get("canvas_usage"), dict):
            d["canvas_usage"] = CanvasUsage(**d["canvas_usage"])
        if isinstance(d.get("navigation"), dict):
            d["navigation"] = NavigationStructure(**d["navigation"])
        if isinstance(d.get("search_functionality"), dict):
            d["search_functionality"] = SearchConfig(**d["search_functionality"])

        # Lists of dataclasses
        _list_map: dict[str, type[Any]] = {
            "thumbnail_structures": ThumbnailGrid,
            "content_types": ContentPattern,
            "repeating_patterns": RepeatingPattern,
            "list_structures": ListStructure,
            "obstacles": ObstaclePattern,
            "obstacle_dismiss_strategies": DismissStrategy,
            "category_tree": CategoryNode,
            "interaction_patterns": InteractionPattern,
            "form_types": FormPattern,
            "api_endpoints": APIEndpoint,
        }
        for field_name, dc_cls in _list_map.items():
            if isinstance(d.get(field_name), list):
                d[field_name] = [
                    dc_cls(**item) if isinstance(item, dict) else item
                    for item in d[field_name]
                ]

        return cls(**d)

    @classmethod
    def from_json(cls, json_str: str) -> SiteProfile:
        """Parse from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def compute_dom_hash(self) -> str:
        """Compute structural DOM hash for change detection."""
        data = json.dumps(
            {
                "total_elements": self.dom_complexity.total_elements,
                "max_depth": self.dom_complexity.max_depth,
                "framework": self.framework,
                "is_spa": self.is_spa,
            },
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]
