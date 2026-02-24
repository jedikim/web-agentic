"""Tests for LLMFirstOrchestrator — LLM-driven automation loop."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.llm_orchestrator import LLMFirstOrchestrator, RunResult
from src.core.selector_cache import CacheHit
from src.core.types import (
    ExtractedElement,
    PageState,
    PatchData,
    StepDefinition,
    VerifyResult,
)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://shopping.naver.com"
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    return page


@pytest.fixture
def mock_executor(mock_page):
    ex = AsyncMock()
    ex.get_page.return_value = mock_page
    ex.screenshot.return_value = b"fake-png"
    return ex


@pytest.fixture
def mock_extractor():
    ext = AsyncMock()
    ext.extract_state.return_value = PageState(
        url="https://shopping.naver.com",
        title="네이버쇼핑",
        visible_text="검색",
    )
    ext.extract_clickables.return_value = [
        ExtractedElement(
            eid="#search-input", type="input", text="검색어를 입력해주세요", visible=True
        ),
    ]
    ext.extract_inputs.return_value = [
        ExtractedElement(
            eid="#search-input", type="input", text="검색어를 입력해주세요", visible=True
        ),
    ]
    return ext


@pytest.fixture
def mock_planner():
    p = AsyncMock()
    p.plan_with_context.return_value = [
        StepDefinition(
            step_id="s1",
            intent="검색창에 노트북 입력",
            node_type="action",
            arguments=["노트북"],
        ),
    ]
    p.select.return_value = PatchData(
        patch_type="selector_fix",
        target="#search-input",
        data={"selected_eid": "#search-input"},
        confidence=0.95,
    )
    p.usage = MagicMock(total_tokens=100, total_cost_usd=0.001)
    return p


@pytest.fixture
def mock_verifier():
    v = AsyncMock()
    v.verify.return_value = VerifyResult(success=True, message="OK")
    return v


@pytest.fixture
def mock_cache():
    c = AsyncMock()
    c.lookup.return_value = None  # cache miss
    return c


@pytest.mark.asyncio
async def test_run_single_step_success(
    mock_executor, mock_extractor, mock_planner, mock_verifier, mock_cache, tmp_path
):
    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=mock_cache,
        screenshot_dir=tmp_path / "screenshots",
    )
    result = await orch.run("노트북 검색")
    assert result.success
    assert len(result.step_results) == 1
    assert result.step_results[0].success


@pytest.mark.asyncio
async def test_run_uses_cache_on_hit(
    mock_executor, mock_extractor, mock_planner, mock_verifier, tmp_path
):
    cache = AsyncMock()
    cache.lookup.return_value = CacheHit(
        selector="#cached-btn", method="click", confidence=0.95
    )

    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=cache,
        screenshot_dir=tmp_path / "screenshots",
    )
    result = await orch.run("노트북 검색")
    assert result.success
    # LLM select should NOT be called (cache hit)
    mock_planner.select.assert_not_called()


@pytest.mark.asyncio
async def test_screenshots_saved(
    mock_executor, mock_extractor, mock_planner, mock_verifier, mock_cache, tmp_path
):
    ss_dir = tmp_path / "screenshots"
    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=mock_cache,
        screenshot_dir=ss_dir,
    )
    result = await orch.run("노트북 검색")
    assert ss_dir.exists()
    pngs = list(ss_dir.glob("*.png"))
    assert len(pngs) >= 1


@pytest.mark.asyncio
async def test_goto_step_no_llm_select(
    mock_executor, mock_extractor, mock_planner, mock_verifier, mock_cache, tmp_path
):
    mock_planner.plan_with_context.return_value = [
        StepDefinition(
            step_id="s1",
            intent="네이버 쇼핑으로 이동",
            node_type="goto",
            arguments=["https://shopping.naver.com"],
        ),
    ]
    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=mock_cache,
        screenshot_dir=tmp_path / "screenshots",
    )
    result = await orch.run("네이버 쇼핑 방문")
    assert result.success
    assert result.step_results[0].method == "GOTO"
    mock_planner.select.assert_not_called()


@pytest.mark.asyncio
async def test_infer_action_type():
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="검색창에 입력", node_type="action")
    ) == "type"
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="버튼 클릭", node_type="action")
    ) == "click"
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="navigate to", node_type="action")
    ) == "goto"
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="press enter", node_type="action")
    ) == "press_key"
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="아래로 스크롤", node_type="action")
    ) == "scroll"
    # node_type takes priority
    assert LLMFirstOrchestrator._infer_action(
        StepDefinition(step_id="s", intent="whatever", node_type="type")
    ) == "type"
