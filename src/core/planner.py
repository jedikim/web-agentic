"""Planner — VLM screenshot-first planning.

The Planner looks at the screen FIRST (not DOM), then plans.

Two-phase approach:
1. check_screen(screenshot) → ScreenState — obstacle detection
2. plan(task, screenshot) → list[StepPlan] — step decomposition

Both phases use VLM (Gemini Flash) with screenshot input.
The Planner always outputs BOTH keyword_weights AND target_viewport_xy
for every step — the runtime decides which path to use.

Prompt versioning:
- Prompts loaded from PromptManager (config/prompts/v3_check_screen/, v3_plan/)
- Inline fallback constants used when PromptManager is not provided.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Protocol

from src.core.types import ScreenState, StepPlan

if TYPE_CHECKING:
    from src.ai.prompt_manager import PromptManager

logger = logging.getLogger(__name__)

# Prompt names for PromptManager lookup
_PROMPT_CHECK_SCREEN = "v3_check_screen"
_PROMPT_PLAN = "v3_plan"

# ---------------------------------------------------------------------------
# Inline fallback prompts — used when PromptManager is not available.
# Canonical versions live in config/prompts/v3_check_screen/v1.txt and
# config/prompts/v3_plan/v1.txt.  Keep these in sync.
# ---------------------------------------------------------------------------

_CHECK_SCREEN_PROMPT = """\
당신은 웹 자동화 에이전트입니다.
스크린샷을 보고 현재 화면에 태스크 실행을 방해하는 요소가 있는지 판단하세요.

방해 요소 (has_obstacle: true):
- 광고 팝업, 이벤트 배너, 쿠키 동의창, 로딩 스플래시, 모달 대화상자
- 화면 전체를 덮는 오버레이

방해 요소가 아닌 것 (has_obstacle: false):
- 검색 자동완성/추천 드롭다운
- 네비게이션 메뉴, 사이드바
- 일반 페이지 콘텐츠 (기사, 상품 목록 등)
- 작은 툴팁, 알림 배지

JSON으로 답하세요:
{
  "has_obstacle": true/false,
  "obstacle_type": "popup" | "ad_banner" | "cookie_consent" | "event_splash" | "modal" | null,
  "obstacle_close_xy": [x, y] | null,
  "obstacle_description": "설명" | null
}

- obstacle_close_xy는 닫기 버튼의 뷰포트 상대 좌표 (0~1, 0~1)
- 방해 요소가 없으면 has_obstacle: false, 나머지 null
- 판단이 애매하면 has_obstacle: false로 답하세요"""

_PLAN_PROMPT_TEMPLATE = """\
당신은 웹 자동화 에이전트입니다.
스크린샷을 보고 태스크를 실행 스텝으로 분해하세요.

중요 원칙:
- **현재 스크린샷에 보이는 요소만** 계획하세요.
- 숨겨진 드롭다운 메뉴, 아직 열리지 않은 하위 메뉴, 접혀 있는 패널의 내부 항목은 추측하지 마세요.
- 메뉴를 열어야 내부가 보인다면, 먼저 메뉴를 여는 스텝 1개만 출력하세요. 열린 후 다시 계획합니다.
- 예: "전체 카테고리 → 스포츠 → 등산복" 3단계 메뉴는 첫 스텝 "전체 카테고리 호버"만 출력.

요소 구별 원칙 (매우 중요):
- 같은 텍스트의 요소가 여러 개 보이면, **주변 라벨이나 섹션명**도 keyword_weights에 포함하세요.
  예: 가격 필터 영역의 검색 버튼 → {{"가격": 0.7, "필터": 0.6, "검색": 0.9, "적용": 0.5}}
  예: 상단 상품 검색 입력창 → {{"상품": 0.7, "검색어": 0.8}}
- type 액션: 어떤 입력 필드인지 구별하는 키워드 필수.
  입력 필드 주변의 라벨(가격, 수량, 검색어 등)을 반드시 포함하세요.
- click 액션에서 적용/확인 버튼: 해당 버튼이 속한 **필터/폼 영역의 키워드**도 포함하세요.
- type 액션에서 입력 필드 구별 (매우 중요):
  - 상단 메인 검색창: "검색", "통합검색", "상품명" 등 — target_viewport_xy 상단 중앙
  - 필터/상세검색 입력: "가격", "최소", "최대", "상세검색" — target_viewport_xy 좌측/하단
  - 반드시 정확한 위치의 target_viewport_xy를 지정하세요.
- 대상 항목이 이미 화면에 보이면 '더보기/펼치기' 버튼을 건너뛰세요.

각 스텝마다 반드시 아래를 모두 출력:
- keyword_weights: 대상 요소와 그 주변에서 보이는 텍스트 키워드와 가중치 (0~1)
  (텍스트가 안 보여도 추측해서 작성. 예: 돋보기 아이콘 → {{"search": 0.8, "검색": 0.8}})
- target_viewport_xy: 대상 요소의 뷰포트 상대 좌표 [x, y] (0~1, 0~1)
- expected_result: 이 액션 후 기대하는 변화. 아래 형식 중 택 1:
  - "URL 변경: /category/sports" (페이지 이동 시)
  - "DOM 존재: .search-results" (같은 페이지 내 변화 시)
  - "화면 변화" (위 둘로 표현 못할 때)

JSON 배열로 답하세요:
[
  {{
    "step_index": 0,
    "action_type": "click" | "type" | "scroll" | "hover" | "press" | "goto" | "wait"
                 | "visual_filter",
    "target_description": "대상 설명",
    "value": "입력값 (type일 때만)" | null,
    "keyword_weights": {{"키워드": 가중치}},
    "target_viewport_xy": [x, y],
    "expected_result": "기대 결과",
    "visual_filter_query": "시각적 필터 조건 (visual_filter일 때만)" | null,
    "visual_complexity": "simple" | "complex" | null
  }}
]

시각적 판별 (visual_filter) — 시각 속성 필터링의 기본 수단:
- 색상, 문양, 소재, 디자인 등 시각적 속성으로 상품을 골라야 할 때 → 반드시 visual_filter.
- 사이트에 색상 필터 UI(체크박스, 드롭다운)가 있어도 사용하지 마세요.
  visual_filter 1개 스텝이 사이트 필터 여러 스텝보다 정확하고 빠릅니다.
- 전형적 흐름: 카테고리 이동 → 비시각 필터(가격, 브랜드) → scroll → visual_filter
- 시스템이 상품 이미지를 자동 감지 → 그리드 병합 → 시각 모델이 판별.
- visual_filter_query: 찾고자 하는 시각적 조건 (예: "빨간색", "긴 소매", "체크 무늬")
- visual_complexity:
  - "simple": 단일 색상, 기본 형태 등 단순한 시각 판별 → CV 모델(RF-DETR)로 충분
  - "complex": 문양, 소재, 디자인, 스타일 등 복합적 판별 → 반드시 VLM 사용

[태스크]: {task}"""


class IPlannerVLM(Protocol):
    """VLM interface — accepts text prompt + image."""

    async def generate_with_image(self, prompt: str, image: bytes) -> str: ...


class Planner:
    """VLM-based planner: screenshot first, then plan.

    Supports optional PromptManager for versioned prompt templates.
    Falls back to inline constants when PromptManager is not provided.

    Usage:
        # Without versioning (backward-compat)
        planner = Planner(vlm=gemini_flash_vlm)

        # With versioned prompts
        from src.ai.prompt_manager import PromptManager
        pm = PromptManager()
        planner = Planner(vlm=gemini_flash_vlm, prompt_manager=pm)

        screen = await planner.check_screen(screenshot_bytes)
        steps = await planner.plan("검색창에 등산복 입력", screenshot_bytes)
    """

    def __init__(
        self,
        vlm: IPlannerVLM,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._vlm = vlm
        self._pm = prompt_manager

    def _get_check_screen_prompt(self) -> str:
        """Load check_screen prompt from PromptManager or inline fallback."""
        if self._pm is not None:
            try:
                return self._pm.get_prompt(_PROMPT_CHECK_SCREEN)
            except KeyError:
                logger.debug(
                    "Prompt %r not found in PromptManager, using inline",
                    _PROMPT_CHECK_SCREEN,
                )
        return _CHECK_SCREEN_PROMPT

    def _get_plan_prompt(self, task: str) -> str:
        """Load plan prompt from PromptManager or inline fallback.

        PromptManager templates use ``$task``; inline uses ``{task}``.
        """
        if self._pm is not None:
            try:
                return self._pm.get_prompt(_PROMPT_PLAN, task=task)
            except KeyError:
                logger.debug(
                    "Prompt %r not found in PromptManager, using inline",
                    _PROMPT_PLAN,
                )
        return _PLAN_PROMPT_TEMPLATE.format(task=task)

    async def check_screen(self, screenshot: bytes) -> ScreenState:
        """Check the screen for obstacles using VLM.

        Args:
            screenshot: PNG screenshot bytes.

        Returns:
            ScreenState with obstacle info.
        """
        prompt = self._get_check_screen_prompt()
        response = await self._vlm.generate_with_image(prompt, screenshot)
        return self._parse_screen_state(response)

    async def plan(
        self, task: str, screenshot: bytes,
        site_knowledge: str = "",
    ) -> list[StepPlan]:
        """Decompose a task into executable steps using VLM.

        Args:
            task: Natural language task description.
            screenshot: PNG screenshot bytes of current page.
            site_knowledge: Markdown site knowledge to inject into prompt.

        Returns:
            List of StepPlan with keyword_weights and target_viewport_xy.
        """
        prompt = self._get_plan_prompt(task)
        if site_knowledge:
            prompt += f"\n\n[사이트 지식]\n{site_knowledge}"
        response = await self._vlm.generate_with_image(prompt, screenshot)
        return self._parse_steps(response)

    def _parse_screen_state(self, response: str) -> ScreenState:
        """Parse VLM response into ScreenState."""
        data = _extract_json_object(response)
        if not data:
            return ScreenState()

        close_xy = data.get("obstacle_close_xy")
        if isinstance(close_xy, list) and len(close_xy) == 2:
            try:
                close_xy = (float(close_xy[0]), float(close_xy[1]))
            except (ValueError, TypeError):
                close_xy = None
        else:
            close_xy = None

        return ScreenState(
            has_obstacle=bool(data.get("has_obstacle", False)),
            obstacle_type=data.get("obstacle_type"),
            obstacle_close_xy=close_xy,
            obstacle_description=data.get("obstacle_description"),
        )

    def _parse_steps(self, response: str) -> list[StepPlan]:
        """Parse VLM response into list of StepPlan."""
        items = _extract_json_array(response)
        if not items:
            logger.warning("Planner: failed to parse steps from response")
            return []

        steps: list[StepPlan] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            kw = item.get("keyword_weights", {})
            if not isinstance(kw, dict):
                kw = {}

            xy = item.get("target_viewport_xy")
            if isinstance(xy, list) and len(xy) == 2:
                try:
                    xy = (float(xy[0]), float(xy[1]))
                except (ValueError, TypeError):
                    xy = None
            else:
                xy = None

            steps.append(StepPlan(
                step_index=item.get("step_index", i),
                action_type=item.get("action_type", "click"),
                target_description=item.get("target_description", ""),
                value=item.get("value"),
                keyword_weights=kw,
                target_viewport_xy=xy,
                expected_result=item.get("expected_result"),
                visual_filter_query=item.get("visual_filter_query"),
                visual_complexity=item.get("visual_complexity"),
            ))

        return steps


def _extract_json_object(text: str) -> dict | None:  # type: ignore[type-arg]
    """Extract the first JSON object from text."""
    # Try to find JSON block in markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    # Try the whole text
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    return None


def _extract_json_array(text: str) -> list | None:  # type: ignore[type-arg]
    """Extract the first JSON array from text."""
    # Try markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON array — match balanced brackets
    bracket_start = text.find("[")
    if bracket_start >= 0:
        depth = 0
        for i in range(bracket_start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[bracket_start:i + 1])
                    except json.JSONDecodeError:
                        break

    # Try the whole text
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    return None
