"""V4 Orchestrator — recon → codegen → runtime → improve loop.

Connects the v4 pipeline modules and returns V3RunResult for
seamless integration with the existing API/UI layer.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from src.codegen.agent import CodeGenAgent
from src.core.v3_orchestrator import V3RunResult
from src.core.v4_result_adapter import workflow_result_to_v3
from src.improve.change_detector import ChangeDetector
from src.improve.failure_analyzer import AnalysisContext, FailureAnalyzer
from src.improve.self_improver import SelfImprover
from src.kb.manager import KBManager
from src.kb.maturity import MaturityTracker
from src.llm.router import LLMRouter
from src.recon.agent import run_recon
from src.runtime.workflow import RuntimeWorkflow

logger = logging.getLogger(__name__)


class V4Orchestrator:
    """Orchestrate the v4 pipeline: recon → codegen → runtime → improve.

    Args:
        kb: Knowledge Base manager.
        llm: LLM router for model dispatch.
        maturity_tracker: Tracks Cold/Warm/Hot maturity per domain.
        change_detector: Detects site changes between runs.
        codegen: Code generation agent.
        runtime: Runtime workflow executor.
        failure_analyzer: 4-level failure classifier.
        improver: Self-improvement dispatcher.
        detector: Optional local object detector (YOLO/RT-DETR).
        vlm: Optional VLM client.
        progress_callback: Optional progress reporting callback.
    """

    def __init__(
        self,
        *,
        kb: KBManager,
        llm: LLMRouter,
        maturity_tracker: MaturityTracker,
        change_detector: ChangeDetector,
        codegen: CodeGenAgent,
        runtime: RuntimeWorkflow,
        failure_analyzer: FailureAnalyzer,
        improver: SelfImprover,
        detector: Any = None,
        vlm: Any = None,
        progress_callback: Any = None,
    ) -> None:
        self._kb = kb
        self._llm = llm
        self._maturity = maturity_tracker
        self._change_detector = change_detector
        self._codegen = codegen
        self._runtime = runtime
        self._analyzer = failure_analyzer
        self._improver = improver
        self._detector = detector
        self._vlm = vlm
        self._progress_cb = progress_callback

    async def run(
        self,
        intent: str,
        browser_adapter: Any,
        *,
        url: str | None = None,
        task_type: str = "general",
        skip_change_detect: bool = False,
    ) -> V3RunResult:
        """Execute the full v4 pipeline.

        Args:
            intent: Natural language task instruction.
            browser_adapter: V4BrowserAdapter wrapping Playwright page.
            url: Current page URL (extracted from browser if None).
            task_type: Task type for codegen strategy.
            skip_change_detect: Skip change detection (e.g. first turn).

        Returns:
            V3RunResult compatible with the API layer.
        """
        t0 = time.monotonic()

        # 1. Extract URL and domain
        if url is None:
            page = await browser_adapter.get_page()
            url = page.url
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or "unknown"

        logger.info("v4 run: domain=%s intent=%r", domain, intent[:80])

        # 2. Change detection (skip on first turn or if disabled)
        if not skip_change_detect:
            try:
                cd_result = await self._change_detector.detect(
                    domain, browser_adapter, self._kb,
                )
                if cd_result.needs_recon:
                    logger.info(
                        "Change detected (score=%.2f), triggering recon",
                        cd_result.score,
                    )
                    await self._run_recon(domain, browser_adapter)
            except Exception:
                logger.warning("Change detection failed, continuing", exc_info=True)

        # 3. KB lookup
        lookup = self._kb.lookup(domain, url)
        maturity = self._maturity.load(domain)

        # 4. Cold start: run recon + codegen if no profile/workflow
        if not lookup.hit or lookup.profile is None:
            logger.info("KB miss for %s — running recon + codegen", domain)
            profile = await self._run_recon(domain, browser_adapter)
            if profile is not None:
                await self._run_codegen(domain, profile, task_type, intent=intent)
                # Re-lookup after codegen
                lookup = self._kb.lookup(domain, url)

        # 5. Runtime execution
        wf_result = await self._runtime.run(
            domain=domain,
            url=url,
            task=intent,
            browser=browser_adapter,
            kb=self._kb,
            maturity=maturity,
        )

        # 6. Record maturity
        self._maturity.record_run(
            domain, success=wf_result.success, llm_calls=wf_result.llm_calls,
        )

        # 7. On failure: analyze + improve + retry once
        if not wf_result.success:
            wf_result = await self._handle_failure(
                wf_result, domain, url, intent, browser_adapter, maturity,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "v4 run complete: domain=%s success=%s elapsed=%.0fms",
            domain, wf_result.success, elapsed_ms,
        )

        return workflow_result_to_v3(wf_result, intent)

    async def _run_recon(self, domain: str, browser: Any) -> Any:
        """Run reconnaissance and return SiteProfile or None."""
        try:
            profile = await run_recon(
                domain,
                browser,
                self._kb,
                detector=self._detector,
                vlm=self._vlm,
                llm=self._llm,
            )
            return profile
        except Exception:
            logger.warning("Recon failed for %s", domain, exc_info=True)
            return None

    async def _run_codegen(
        self, domain: str, profile: Any, task_type: str,
        *, intent: str = "",
    ) -> None:
        """Run code generation and save bundle to KB."""
        try:
            await self._codegen.generate_bundle(
                domain=domain,
                profile=profile,
                task_type=task_type,
                kb=self._kb,
                llm=self._llm,
                intent=intent,
            )
        except Exception:
            logger.warning("Codegen failed for %s", domain, exc_info=True)

    async def _handle_failure(
        self,
        wf_result: Any,
        domain: str,
        url: str,
        intent: str,
        browser: Any,
        maturity: Any,
    ) -> Any:
        """Analyze failure, attempt improvement, retry once."""
        evidence = wf_result.failure_evidence
        if evidence is None:
            error_msg = wf_result.error or "unknown"
            evidence = await self._analyzer.analyze(
                error_msg,
                AnalysisContext(url=url),
            )

        # Determine URL pattern for KB patching
        url_pattern = self._kb._match_url_pattern(domain, url) or "default"

        try:
            improvement = await self._improver.improve(
                evidence=evidence,
                domain=domain,
                url_pattern=url_pattern,
                kb=self._kb,
                llm=self._llm,
            )
            logger.info(
                "Improvement action=%s detail=%s",
                improvement.action_taken, improvement.detail[:80],
            )
        except Exception:
            logger.warning("Self-improvement failed", exc_info=True)
            return wf_result

        if improvement.needs_recon:
            await self._run_recon(domain, browser)

        # Retry once
        try:
            retry_result = await self._runtime.run(
                domain=domain,
                url=url,
                task=intent,
                browser=browser,
                kb=self._kb,
                maturity=maturity,
            )
            self._maturity.record_run(
                domain,
                success=retry_result.success,
                llm_calls=retry_result.llm_calls,
            )
            return retry_result
        except Exception:
            logger.warning("Retry execution failed", exc_info=True)
            return wf_result
