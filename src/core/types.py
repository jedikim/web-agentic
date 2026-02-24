"""Core type definitions shared across all modules.

Every module communicates through these data types.
See docs/PRD.md and docs/ARCHITECTURE.md for design rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from playwright.async_api import Page


# ── Failure Codes ────────────────────────────────────

class FailureCode(str, Enum):
    """Failure classification codes used by F(Fallback Router)."""
    SELECTOR_NOT_FOUND = "SelectorNotFound"
    NOT_INTERACTABLE = "NotInteractable"
    STATE_NOT_CHANGED = "StateNotChanged"
    VISUAL_AMBIGUITY = "VisualAmbiguity"
    NETWORK_ERROR = "NetworkError"
    QUEUE_DETECTED = "QueueDetected"
    CAPTCHA_DETECTED = "CaptchaDetected"
    AUTH_REQUIRED = "AuthRequired"
    DYNAMIC_LAYOUT = "DynamicLayout"


# ── Exceptions ───────────────────────────────────────

class AutomationError(Exception):
    """Base exception for all automation errors."""
    failure_code: FailureCode | None = None


class SelectorNotFoundError(AutomationError):
    """Element matching the selector was not found."""
    failure_code = FailureCode.SELECTOR_NOT_FOUND


class NotInteractableError(AutomationError):
    """Element exists but cannot be interacted with."""
    failure_code = FailureCode.NOT_INTERACTABLE


class StateNotChangedError(AutomationError):
    """Action executed but page state did not change as expected."""
    failure_code = FailureCode.STATE_NOT_CHANGED


class VisualAmbiguityError(AutomationError):
    """Multiple visually similar elements found; cannot determine target."""
    failure_code = FailureCode.VISUAL_AMBIGUITY


class NetworkError(AutomationError):
    """Network request failed or timed out."""
    failure_code = FailureCode.NETWORK_ERROR


class CaptchaDetectedError(AutomationError):
    """CAPTCHA or challenge detected — requires human handoff."""
    failure_code = FailureCode.CAPTCHA_DETECTED


class AuthRequiredError(AutomationError):
    """Authentication (login/2FA) required."""
    failure_code = FailureCode.AUTH_REQUIRED


class BudgetExceededError(AutomationError):
    """Token/cost budget exceeded for this task."""


# ── Data Types ───────────────────────────────────────

@dataclass(frozen=True)
class ExtractedElement:
    """A single interactive element extracted from the DOM.

    Attributes:
        eid: Unique element identifier (CSS selector or generated ID).
        type: Element category (input, button, link, tab, option, card, icon, image).
        text: Visible text content (truncated).
        role: ARIA role if present.
        bbox: Bounding box as (x, y, width, height).
        visible: Whether the element is currently visible.
        parent_context: Semantic context from parent container.
    """
    eid: str
    type: str
    text: str | None = None
    role: str | None = None
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    visible: bool = True
    parent_context: str | None = None


@dataclass(frozen=True)
class ProductData:
    """Extracted product information from an e-commerce page."""
    name: str
    price: str | None = None
    url: str | None = None
    image_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageState:
    """Snapshot of current page state for rule matching.

    Attributes:
        url: Current page URL.
        title: Page title.
        visible_text: Truncated visible text (for heuristic matching).
        element_count: Total interactive element count.
        has_popup: Whether a modal/popup is detected.
        has_captcha: Whether a CAPTCHA is detected.
        scroll_position: Current scroll Y offset.
    """
    url: str
    title: str
    visible_text: str = ""
    element_count: int = 0
    has_popup: bool = False
    has_captcha: bool = False
    scroll_position: int = 0


@dataclass(frozen=True)
class PatchData:
    """LLM output — always a structured patch, never free-form code.

    Attributes:
        patch_type: One of selector_fix, param_change, rule_add, strategy_switch.
        target: Module or selector being patched.
        data: Patch payload.
        confidence: LLM's confidence score (0.0–1.0).
    """
    patch_type: str
    target: str
    data: dict[str, Any]
    confidence: float


@dataclass
class StepResult:
    """Result of a single step execution.

    Attributes:
        step_id: Unique step identifier.
        success: Whether the step succeeded.
        method: Resolution method (R, L1, L2, YOLO, VLM1, VLM2, H).
        tokens_used: Total LLM tokens consumed.
        latency_ms: Execution time in milliseconds.
        cost_usd: Estimated cost in USD.
        failure_code: Failure code if unsuccessful.
    """
    step_id: str
    success: bool
    method: str = "R"
    tokens_used: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    failure_code: FailureCode | None = None


@dataclass(frozen=True)
class ClickOptions:
    """Options for click actions."""
    button: str = "left"
    click_count: int = 1
    force: bool = False
    timeout_ms: int = 5000


@dataclass(frozen=True)
class WaitCondition:
    """Condition to wait for before proceeding."""
    type: str  # selector, url, text, network_idle, timeout
    value: str = ""
    timeout_ms: int = 10000


@dataclass(frozen=True)
class VerifyCondition:
    """Condition to verify after an action."""
    type: str  # url_changed, url_contains, element_visible, element_gone, text_present, network_idle
    value: str = ""
    timeout_ms: int = 5000


@dataclass
class VerifyResult:
    """Result of a verification check."""
    success: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleMatch:
    """A successful rule match from R(Rule Engine)."""
    rule_id: str
    selector: str
    method: str  # click, type, select, scroll, wait
    arguments: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass(frozen=True)
class RuleDefinition:
    """A rule definition for the Rule Engine."""
    rule_id: str
    category: str  # popup, search, sort, filter, pagination, login, error
    intent_pattern: str
    selector: str
    method: str = "click"
    arguments: list[str] = field(default_factory=list)
    site_pattern: str = "*"
    priority: int = 0


@dataclass(frozen=True)
class RecoveryPlan:
    """A recovery plan produced by F(Fallback Router)."""
    strategy: str  # retry, escalate_llm, escalate_vision, human_handoff, skip
    tier: int = 1  # 1=cheapest, 2=mid, 3=expensive
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepDefinition:
    """A single step in a workflow."""
    step_id: str
    intent: str
    node_type: str = "action"  # action, extract, decide, verify, branch, loop, wait, recover, handoff
    selector: str | None = None
    arguments: list[str] = field(default_factory=list)
    verify_condition: VerifyCondition | None = None
    max_attempts: int = 3
    timeout_ms: int = 10000


# ── Step Context (mutable, used during execution) ────

@dataclass
class StepContext:
    """Mutable context available during step execution."""
    step: StepDefinition
    page_state: PageState
    attempt: int = 0
    previous_error: AutomationError | None = None
    working_memory: dict[str, Any] = field(default_factory=dict)


# ── Protocol Interfaces ──────────────────────────────

class IExecutor(Protocol):
    """Browser automation interface — X module."""
    async def goto(self, url: str) -> None: ...
    async def click(self, selector: str, options: ClickOptions | None = None) -> None: ...
    async def type_text(self, selector: str, text: str) -> None: ...
    async def press_key(self, key: str) -> None: ...
    async def scroll(self, direction: str = "down", amount: int = 300) -> None: ...
    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes: ...
    async def wait_for(self, condition: WaitCondition) -> None: ...
    async def get_page(self) -> Page: ...


class IExtractor(Protocol):
    """DOM extraction interface — E module."""
    async def extract_inputs(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_clickables(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_products(self, page: Page) -> list[ProductData]: ...
    async def extract_state(self, page: Page) -> PageState: ...


class IRuleEngine(Protocol):
    """Rule matching interface — R module."""
    def match(self, intent: str, context: PageState) -> RuleMatch | None: ...
    def heuristic_select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> str | None: ...
    def register_rule(self, rule: RuleDefinition) -> None: ...


class IVerifier(Protocol):
    """Post-action verification interface — V module."""
    async def verify(self, condition: VerifyCondition, page: Page) -> VerifyResult: ...


class IFallbackRouter(Protocol):
    """Failure classification and routing interface — F module."""
    def classify(self, error: Exception, context: StepContext) -> FailureCode: ...
    def route(self, failure: FailureCode) -> RecoveryPlan: ...


class ILLMPlanner(Protocol):
    """LLM-based planning interface — L module."""
    async def plan(self, instruction: str) -> list[StepDefinition]: ...
    async def select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> PatchData: ...


class IMemoryManager(Protocol):
    """4-layer memory interface."""
    def get_working(self, key: str) -> Any: ...
    def set_working(self, key: str, value: Any) -> None: ...
    async def save_episode(self, task_id: str, data: dict[str, Any]) -> None: ...
    async def load_episode(self, task_id: str) -> dict[str, Any] | None: ...
    async def query_policy(self, intent: str, site: str) -> RuleMatch | None: ...
    async def save_policy(self, rule: RuleDefinition, success_count: int) -> None: ...


# ── Vision Protocol Interfaces ──────────────────────


class IYOLODetector(Protocol):
    """YOLO local detection interface."""

    async def detect(self, screenshot: bytes) -> list[Any]: ...
    async def detect_elements(self, screenshot: bytes) -> list[ExtractedElement]: ...


class IVLMClient(Protocol):
    """VLM API client interface."""

    async def select_element(
        self, screenshot: bytes, candidates: list[ExtractedElement], intent: str
    ) -> PatchData: ...


class ICoordMapper(Protocol):
    """Coordinate reverse mapping interface."""

    def find_closest_element(
        self, point: tuple[int, int], candidates: list[ExtractedElement]
    ) -> ExtractedElement | None: ...


# ── Progress Callback Types ─────────────────────────


class ProgressEvent(str, Enum):
    """Events emitted during orchestration."""

    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    LEVEL_CHANGED = "level_changed"
    RUN_COMPLETED = "run_completed"


@dataclass(frozen=True)
class ProgressInfo:
    """Information emitted with progress events."""

    event: ProgressEvent
    step_id: str = ""
    step_index: int = 0
    total_steps: int = 0
    method: str = ""
    attempt: int = 0
    message: str = ""
    result: StepResult | None = None


class IProgressCallback(Protocol):
    """Callback interface for progress events."""

    def on_progress(self, info: ProgressInfo) -> None: ...
