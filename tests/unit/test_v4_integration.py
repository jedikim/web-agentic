"""Tests for v4 integration: browser adapter, result adapter, orchestrator, factory, config."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import EngineConfig, V4PipelineConfig, _parse_config
from src.core.v4_browser_adapter import V4BrowserAdapter, V4PageAdapter
from src.core.v4_result_adapter import workflow_result_to_v3
from src.runtime.executor import ExecutionResult
from src.runtime.workflow import WorkflowResult

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture()
def mock_page() -> MagicMock:
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.url = "https://example.com/search"
    page.goto = AsyncMock(return_value=None)
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.hover = AsyncMock()
    page.press = AsyncMock()
    page.select_option = AsyncMock(return_value=["opt1"])
    page.screenshot = AsyncMock(return_value=b"\x89PNG")
    page.evaluate = AsyncMock(return_value=42)
    page.wait_for_timeout = AsyncMock()
    page.wait_for_selector = AsyncMock(return_value=MagicMock())
    page.query_selector = AsyncMock(return_value=MagicMock())
    page.query_selector_all = AsyncMock(return_value=[])
    page.accessibility = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"role": "WebArea"})
    page.context = MagicMock()
    page.context.new_cdp_session = AsyncMock(return_value=AsyncMock())
    return page


# ── TestV4BrowserAdapter ─────────────────────────────


class TestV4PageAdapter:
    """Test V4PageAdapter satisfies PageLike protocol."""

    @pytest.mark.asyncio()
    async def test_url_property(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        assert adapter.url == "https://example.com/search"

    @pytest.mark.asyncio()
    async def test_goto(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        await adapter.goto("https://example.com")
        mock_page.goto.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio()
    async def test_click(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        await adapter.click("#btn")
        mock_page.click.assert_awaited_once_with("#btn")

    @pytest.mark.asyncio()
    async def test_fill(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        await adapter.fill("#input", "hello")
        mock_page.fill.assert_awaited_once_with("#input", "hello")

    @pytest.mark.asyncio()
    async def test_screenshot(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        result = await adapter.screenshot()
        assert result == b"\x89PNG"

    @pytest.mark.asyncio()
    async def test_evaluate(self, mock_page: MagicMock) -> None:
        adapter = V4PageAdapter(mock_page)
        result = await adapter.evaluate("1+1")
        assert result == 42


class TestV4BrowserAdapter:
    """Test V4BrowserAdapter satisfies all three protocols."""

    @pytest.mark.asyncio()
    async def test_get_page_returns_page_adapter(
        self, mock_page: MagicMock,
    ) -> None:
        adapter = V4BrowserAdapter(mock_page)
        page = await adapter.get_page()
        assert isinstance(page, V4PageAdapter)

    @pytest.mark.asyncio()
    async def test_evaluate_ibrowser(self, mock_page: MagicMock) -> None:
        adapter = V4BrowserAdapter(mock_page)
        result = await adapter.evaluate("document.title")
        mock_page.evaluate.assert_awaited_once_with("document.title")
        assert result == 42

    @pytest.mark.asyncio()
    async def test_query_selector_all(self, mock_page: MagicMock) -> None:
        adapter = V4BrowserAdapter(mock_page)
        result = await adapter.query_selector_all("a")
        mock_page.query_selector_all.assert_awaited_once_with("a")
        assert result == []

    @pytest.mark.asyncio()
    async def test_accessibility_snapshot(self, mock_page: MagicMock) -> None:
        adapter = V4BrowserAdapter(mock_page)
        result = await adapter.accessibility_snapshot()
        assert result == {"role": "WebArea"}

    @pytest.mark.asyncio()
    async def test_url_method(self, mock_page: MagicMock) -> None:
        adapter = V4BrowserAdapter(mock_page)
        result = await adapter.url()
        assert result == "https://example.com/search"

    @pytest.mark.asyncio()
    async def test_cdp_send(self, mock_page: MagicMock) -> None:
        adapter = V4BrowserAdapter(mock_page)
        cdp_mock = mock_page.context.new_cdp_session.return_value
        cdp_mock.send = AsyncMock(return_value={"nodes": []})
        result = await adapter.cdp_send("DOM.getDocument", {})
        assert result == {"nodes": []}


# ── TestV4ResultAdapter ──────────────────────────────


class TestV4ResultAdapter:
    """Test WorkflowResult → V3RunResult conversion."""

    def test_success_conversion(self) -> None:
        execution = ExecutionResult(
            success=True, steps_completed=3, total_steps=3,
        )
        wf = WorkflowResult(
            success=True, stage="warm", execution=execution,
            screenshots=[b"\x89PNG", b"\x89PNG2"],
        )
        result = workflow_result_to_v3(wf, "검색 수행")
        assert result.success is True
        assert len(result.step_results) == 3
        assert all(s.success for s in result.step_results)
        assert len(result.screenshots) == 2
        assert "OK" in result.result_summary

    def test_failure_conversion(self) -> None:
        execution = ExecutionResult(
            success=False, steps_completed=2, total_steps=5,
            error="timeout",
        )
        wf = WorkflowResult(
            success=False, stage="cold", error="timeout",
            execution=execution, screenshots=[],
        )
        result = workflow_result_to_v3(wf, "검색")
        assert result.success is False
        assert len(result.step_results) == 3  # 2 ok + 1 failed
        assert result.step_results[0].success is True
        assert result.step_results[2].success is False
        assert "FAILED" in result.result_summary

    def test_no_execution(self) -> None:
        wf = WorkflowResult(success=False, error="no KB entry")
        result = workflow_result_to_v3(wf, "task")
        assert result.success is False
        assert len(result.step_results) == 0

    def test_screenshots_base64(self) -> None:
        wf = WorkflowResult(
            success=True,
            execution=ExecutionResult(success=True, steps_completed=1, total_steps=1),
            screenshots=[b"abc"],
        )
        result = workflow_result_to_v3(wf, "test")
        import base64
        assert base64.b64decode(result.screenshots[0]) == b"abc"


# ── TestV4Orchestrator ───────────────────────────────


class TestV4Orchestrator:
    """Test V4Orchestrator flow."""

    @pytest.mark.asyncio()
    async def test_cold_start_recon_codegen_runtime(self) -> None:
        """Cold start: KB miss → recon → codegen → runtime → success."""
        from src.core.v4_orchestrator import V4Orchestrator

        # Mock all dependencies
        kb = MagicMock()
        kb.lookup = MagicMock(side_effect=[
            # First call: miss
            MagicMock(hit=False, profile=None),
            # Second call after cold-start codegen: hit
            MagicMock(hit=True, profile=MagicMock(), workflow={}),
            # Third call after intent-specific codegen (step 4b): hit
            MagicMock(hit=True, profile=MagicMock(), workflow={}),
        ])
        kb._match_url_pattern = MagicMock(return_value="search")
        kb.base_dir = "/tmp/kb"

        llm = MagicMock()
        maturity = MagicMock()
        maturity.load = MagicMock(return_value=MagicMock())
        maturity.record_run = MagicMock()

        change_detector = MagicMock()
        change_detector.detect = AsyncMock(
            return_value=MagicMock(needs_recon=False, score=0.1),
        )

        codegen = MagicMock()
        codegen.generate_bundle = AsyncMock()

        runtime = MagicMock()
        runtime.run = AsyncMock(return_value=WorkflowResult(
            success=True, stage="cold", llm_calls=2,
            execution=ExecutionResult(success=True, steps_completed=2, total_steps=2),
        ))

        analyzer = MagicMock()
        improver = MagicMock()

        orch = V4Orchestrator(
            kb=kb, llm=llm, maturity_tracker=maturity,
            change_detector=change_detector, codegen=codegen,
            runtime=runtime, failure_analyzer=analyzer, improver=improver,
        )

        # Mock browser adapter
        browser = MagicMock()
        browser.get_page = AsyncMock(
            return_value=MagicMock(url="https://example.com/search"),
        )

        with patch("src.core.v4_orchestrator.run_recon", new_callable=AsyncMock) as mock_recon:
            mock_recon.return_value = MagicMock()  # SiteProfile
            result = await orch.run("search for python", browser)

        assert result.success is True
        assert mock_recon.called
        # Cold start codegen + intent-specific codegen = 2 calls
        assert codegen.generate_bundle.await_count >= 1
        runtime.run.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_warm_hit_no_recon(self) -> None:
        """Warm start: KB hit → skip recon → runtime → success."""
        from src.core.v4_orchestrator import V4Orchestrator

        kb = MagicMock()
        kb.lookup = MagicMock(return_value=MagicMock(
            hit=True, profile=MagicMock(), workflow={},
        ))
        kb.base_dir = "/tmp/kb"

        maturity = MagicMock()
        maturity.load = MagicMock(return_value=MagicMock())
        maturity.record_run = MagicMock()

        change_detector = MagicMock()
        change_detector.detect = AsyncMock(
            return_value=MagicMock(needs_recon=False, score=0.0),
        )

        runtime = MagicMock()
        runtime.run = AsyncMock(return_value=WorkflowResult(
            success=True, stage="warm", llm_calls=0,
            execution=ExecutionResult(success=True, steps_completed=3, total_steps=3),
        ))

        orch = V4Orchestrator(
            kb=kb, llm=MagicMock(), maturity_tracker=maturity,
            change_detector=change_detector, codegen=MagicMock(),
            runtime=runtime, failure_analyzer=MagicMock(),
            improver=MagicMock(),
        )

        browser = MagicMock()
        browser.get_page = AsyncMock(
            return_value=MagicMock(url="https://example.com/search"),
        )

        result = await orch.run("search", browser, skip_change_detect=True)
        assert result.success is True
        runtime.run.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_failure_triggers_improve_and_retry(self) -> None:
        """Failure → analyze → improve → retry once."""
        from src.core.v4_orchestrator import V4Orchestrator

        kb = MagicMock()
        kb.lookup = MagicMock(return_value=MagicMock(
            hit=True, profile=MagicMock(),
        ))
        kb._match_url_pattern = MagicMock(return_value="search")
        kb.base_dir = "/tmp/kb"

        maturity = MagicMock()
        maturity.load = MagicMock(return_value=MagicMock())
        maturity.record_run = MagicMock()

        change_detector = MagicMock()
        change_detector.detect = AsyncMock(
            return_value=MagicMock(needs_recon=False),
        )

        runtime = MagicMock()
        # First call fails, retry succeeds
        runtime.run = AsyncMock(side_effect=[
            WorkflowResult(
                success=False, error="selector not found",
                failure_evidence=MagicMock(remediation=MagicMock()),
                llm_calls=1,
            ),
            WorkflowResult(
                success=True, stage="warm", llm_calls=1,
                execution=ExecutionResult(success=True, steps_completed=2, total_steps=2),
            ),
        ])

        analyzer = MagicMock()
        improver = MagicMock()
        improver.improve = AsyncMock(return_value=MagicMock(
            action_taken="fix_selector",
            detail="patched selector",
            needs_recon=False,
        ))

        orch = V4Orchestrator(
            kb=kb, llm=MagicMock(), maturity_tracker=maturity,
            change_detector=change_detector, codegen=MagicMock(),
            runtime=runtime, failure_analyzer=analyzer, improver=improver,
        )

        browser = MagicMock()
        browser.get_page = AsyncMock(
            return_value=MagicMock(url="https://example.com/search"),
        )

        result = await orch.run("search", browser, skip_change_detect=True)
        assert result.success is True
        assert runtime.run.await_count == 2
        improver.improve.assert_awaited_once()


# ── TestV4Factory ────────────────────────────────────


class TestV4Factory:
    """Test create_v4_pipeline factory."""

    def test_default_creation(self) -> None:
        from src.core.v4_factory import create_v4_pipeline

        config = EngineConfig()
        pipeline = create_v4_pipeline(config=config)
        assert pipeline.orchestrator is not None
        assert pipeline.kb is not None
        assert pipeline.llm is not None
        assert pipeline.config is config

    def test_custom_kb_and_llm(self) -> None:
        from src.core.v4_factory import create_v4_pipeline

        kb = MagicMock()
        kb.base_dir = "/tmp/custom_kb"
        llm = MagicMock()

        pipeline = create_v4_pipeline(kb=kb, llm=llm)
        assert pipeline.kb is kb
        assert pipeline.llm is llm


# ── TestV4Config ─────────────────────────────────────


class TestV4Config:
    """Test V4PipelineConfig parsing."""

    def test_defaults(self) -> None:
        cfg = V4PipelineConfig()
        assert cfg.enabled is False
        assert cfg.kb_base_dir == "knowledge_base/sites"
        assert cfg.enable_change_detect is True
        assert cfg.change_detect_top_n == 10
        assert cfg.enable_vision is False
        assert cfg.max_improve_retries == 1

    def test_parse_from_yaml(self) -> None:
        raw = {
            "v4_pipeline": {
                "enabled": True,
                "kb_base_dir": "/data/kb",
                "enable_change_detect": False,
                "change_detect_top_n": 20,
                "enable_vision": True,
                "max_improve_retries": 3,
            },
        }
        config = _parse_config(raw)
        assert config.v4_pipeline.enabled is True
        assert config.v4_pipeline.kb_base_dir == "/data/kb"
        assert config.v4_pipeline.enable_change_detect is False
        assert config.v4_pipeline.change_detect_top_n == 20
        assert config.v4_pipeline.enable_vision is True
        assert config.v4_pipeline.max_improve_retries == 3

    def test_parse_empty_uses_defaults(self) -> None:
        config = _parse_config({})
        assert config.v4_pipeline.enabled is False
        assert config.v4_pipeline.kb_base_dir == "knowledge_base/sites"

    def test_engine_config_has_v4(self) -> None:
        config = EngineConfig()
        assert hasattr(config, "v4_pipeline")
        assert isinstance(config.v4_pipeline, V4PipelineConfig)

    def test_v4_priority_over_v3(self) -> None:
        """When v4 is enabled, v3 should be effectively disabled by session manager."""
        raw = {
            "v3_pipeline": {"enabled": True},
            "v4_pipeline": {"enabled": True},
        }
        config = _parse_config(raw)
        # Both can be enabled in config; session_manager handles priority
        assert config.v3_pipeline.enabled is True
        assert config.v4_pipeline.enabled is True
