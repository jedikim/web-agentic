"""Planner — VLM screenshot-first planning.

The Planner looks at the screen FIRST (not DOM), then plans.

Two-phase approach:
1. check_screen(screenshot) → ScreenState — obstacle detection
2. plan(task, screenshot) → list[StepPlan] — step decomposition

Both phases use VLM (Gemini Flash) with screenshot input.
The Planner always outputs BOTH keyword_weights AND target_viewport_xy
for every step — the runtime decides which path to use.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from src.core.types import ScreenState, StepPlan

logger = logging.getLogger(__name__)

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

각 스텝마다 반드시 아래를 모두 출력:
- keyword_weights: 대상 요소에서 보이는 텍스트 키워드와 가중치 (0~1)
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
    "action_type": "click" | "type" | "scroll" | "hover" | "press" | "goto" | "wait",
    "target_description": "대상 설명",
    "value": "입력값 (type일 때만)" | null,
    "keyword_weights": {{"키워드": 가중치}},
    "target_viewport_xy": [x, y],
    "expected_result": "기대 결과"
  }}
]

[태스크]: {task}"""


class IPlannerVLM(Protocol):
    """VLM interface — accepts text prompt + image."""

    async def generate_with_image(self, prompt: str, image: bytes) -> str: ...


class Planner:
    """VLM-based planner: screenshot first, then plan.

    Usage:
        planner = Planner(vlm=gemini_flash_vlm)
        screen = await planner.check_screen(screenshot_bytes)
        steps = await planner.plan("검색창에 등산복 입력", screenshot_bytes)
    """

    def __init__(self, vlm: IPlannerVLM) -> None:
        self._vlm = vlm

    async def check_screen(self, screenshot: bytes) -> ScreenState:
        """Check the screen for obstacles using VLM.

        Args:
            screenshot: PNG screenshot bytes.

        Returns:
            ScreenState with obstacle info.
        """
        response = await self._vlm.generate_with_image(
            _CHECK_SCREEN_PROMPT, screenshot,
        )
        return self._parse_screen_state(response)

    async def plan(self, task: str, screenshot: bytes) -> list[StepPlan]:
        """Decompose a task into executable steps using VLM.

        Args:
            task: Natural language task description.
            screenshot: PNG screenshot bytes of current page.

        Returns:
            List of StepPlan with keyword_weights and target_viewport_xy.
        """
        prompt = _PLAN_PROMPT_TEMPLATE.format(task=task)
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
            ))

        return steps


def _extract_json_object(text: str) -> dict | None:  # type: ignore[type-arg]
    """Extract the first JSON object from text."""
    # Try to find JSON block in markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    # Try the whole text
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    return None


def _extract_json_array(text: str) -> list | None:  # type: ignore[type-arg]
    """Extract the first JSON array from text."""
    # Try markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))  # type: ignore[no-any-return]
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
                        return json.loads(text[bracket_start:i + 1])  # type: ignore[no-any-return]
                    except json.JSONDecodeError:
                        break

    # Try the whole text
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    return None
