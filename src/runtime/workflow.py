"""Runtime workflow — the main KB-backed execution loop.

Flow: KB lookup -> execute bundle -> verify -> record run -> return.
If the KB has no bundle (cold miss), returns an error indicating codegen
is needed. If verification fails, returns failure with evidence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.kb.manager import KBManager
from src.models.bundle import GeneratedBundle
from src.models.failure import FailureEvidence, FailureType
from src.models.maturity import MaturityState
from src.runtime.executor import BrowserLike, BundleExecutor, ExecutionResult
from src.runtime.verifier import (
    ExpectedOutcome,
    ResultVerifier,
    VerificationResult,
)

logger = logging.getLogger(__name__)


# ── Result dataclass ──


@dataclass
class WorkflowResult:
    """Outcome of a full runtime workflow execution."""

    success: bool = False
    stage: str = "cold"  # "cold" | "warm" | "hot"
    bundle_version: int = 0
    duration_ms: float = 0.0
    llm_calls: int = 0
    error: str | None = None
    failure_evidence: FailureEvidence | None = None
    execution: ExecutionResult | None = None
    verification: VerificationResult | None = None
    screenshots: list[bytes] = field(default_factory=list)


# ── Workflow ──


class RuntimeWorkflow:
    """Main execution loop backed by the Knowledge Base.

    Orchestrates: KB lookup -> bundle execution -> verification ->
    result recording.
    """

    def __init__(
        self,
        *,
        executor: BundleExecutor | None = None,
        verifier: ResultVerifier | None = None,
    ) -> None:
        self._executor = executor or BundleExecutor()
        self._verifier = verifier or ResultVerifier()

    async def run(
        self,
        domain: str,
        url: str,
        task: str,
        browser: BrowserLike,
        kb: KBManager,
        expected: ExpectedOutcome | None = None,
        maturity: MaturityState | None = None,
    ) -> WorkflowResult:
        """Execute the full runtime workflow.

        Args:
            domain: Target site domain (e.g. "shopping.naver.com").
            url: Full URL to automate.
            task: Human-readable task description.
            browser: Browser wrapper for Playwright access.
            kb: Knowledge Base manager for artifact lookup.
            expected: Optional verification criteria. If None, skips
                verification.
            maturity: Optional maturity state tracker. If provided,
                records run outcome for stage progression.

        Returns:
            WorkflowResult with execution details and metrics.
        """
        t0 = time.monotonic()
        result = WorkflowResult()

        # ── 1. KB Lookup ──
        lookup = kb.lookup(domain, url)
        result.stage = lookup.stage

        if not lookup.hit or lookup.workflow is None:
            result.duration_ms = (time.monotonic() - t0) * 1000
            result.error = (
                f"KB miss for {domain} ({lookup.reason}): "
                "codegen required"
            )
            logger.info(
                "KB miss for %s (reason=%s), codegen needed",
                domain, lookup.reason,
            )
            self._record_run(
                kb, domain, task, result, url, maturity
            )
            return result

        logger.info(
            "KB hit for %s: stage=%s, reason=%s",
            domain, lookup.stage, lookup.reason,
        )

        # ── 2. Build bundle ──
        bundle = self._build_bundle(lookup.workflow, lookup.stage)
        result.bundle_version = bundle.version

        # ── 3. Execute ──
        exec_result = await self._executor.execute(
            bundle, browser, task
        )
        result.execution = exec_result
        result.screenshots = exec_result.screenshots

        if not exec_result.success:
            result.duration_ms = (time.monotonic() - t0) * 1000
            result.error = exec_result.error
            result.failure_evidence = exec_result.failure_evidence
            logger.warning(
                "Execution failed for %s: %s", domain, exec_result.error
            )
            self._record_run(
                kb, domain, task, result, url, maturity
            )
            return result

        # ── 4. Verify ──
        if expected is not None:
            verification = await self._verifier.verify(
                expected, browser
            )
            result.verification = verification

            if not verification.passed:
                result.duration_ms = (time.monotonic() - t0) * 1000
                result.error = (
                    f"Verification failed: {verification.reason}"
                )
                result.failure_evidence = FailureEvidence(
                    failure_type=FailureType.VERIFICATION_FAILED,
                    error_message=verification.reason,
                    url=url,
                )
                logger.warning(
                    "Verification failed for %s: %s",
                    domain, verification.reason,
                )
                self._record_run(
                    kb, domain, task, result, url, maturity
                )
                return result

        # ── 5. Success ──
        result.success = True
        result.duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Workflow success for %s: stage=%s, %.0fms",
            domain, result.stage, result.duration_ms,
        )
        self._record_run(
            kb, domain, task, result, url, maturity
        )
        return result

    @staticmethod
    def _build_bundle(
        workflow: dict[str, Any],
        stage: str,
    ) -> GeneratedBundle:
        """Construct a GeneratedBundle from KB workflow data.

        Args:
            workflow: Raw workflow DSL dict from KB.
            stage: Current maturity stage.

        Returns:
            GeneratedBundle ready for execution.
        """
        version = workflow.get("version", 1)
        strategy = workflow.get("strategy", "dom_only")
        return GeneratedBundle(
            workflow_dsl=workflow,
            strategy=strategy,
            version=version,
        )

    @staticmethod
    def _record_run(
        kb: KBManager,
        domain: str,
        task: str,
        result: WorkflowResult,
        url: str,
        maturity: MaturityState | None,
    ) -> None:
        """Persist run result to KB history and update maturity.

        Args:
            kb: Knowledge Base manager.
            domain: Target domain.
            task: Task description.
            result: Workflow outcome.
            url: Target URL.
            maturity: Optional maturity state to update.
        """
        record: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "url": url,
            "success": result.success,
            "stage": result.stage,
            "duration_ms": result.duration_ms,
            "llm_calls": result.llm_calls,
            "bundle_version": result.bundle_version,
            "error": result.error,
        }
        try:
            kb.append_run(domain, record)
        except Exception as exc:
            logger.warning("Failed to record run: %s", exc)

        if maturity is not None:
            maturity.record_run(
                success=result.success,
                llm_calls=result.llm_calls,
            )
