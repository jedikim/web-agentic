"""Integration tests for the PoC runner script (scripts/run_poc.py).

All tests are mocked — no real browser or API calls.
Tests verify:
- create_engine returns correct types
- Workflow file loading
- Iteration loop
- Result JSON structure
- Summary output format
- Benchmark script components
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure scripts directory is importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.orchestrator import Orchestrator  # noqa: E402
from src.core.types import (  # noqa: E402
    FailureCode,
    StepResult,
)
from src.workflow.dsl_parser import parse_workflow  # noqa: E402

# ── 1. Workflow File Loading ─────────────────────────


class TestWorkflowLoading:
    """Test that the Naver Shopping workflow YAML loads correctly."""

    def test_naver_workflow_file_exists(self) -> None:
        """naver_shopping.yaml exists in config/workflows."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        assert path.exists(), f"Missing workflow file: {path}"

    def test_naver_workflow_parses_correctly(self) -> None:
        """naver_shopping.yaml parses into valid StepDefinitions."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        steps = parse_workflow(path)

        assert isinstance(steps, list)
        assert len(steps) == 11  # 11 steps in the workflow

    def test_naver_workflow_step_ids(self) -> None:
        """All step IDs are unique and match expected names."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        steps = parse_workflow(path)

        expected_ids = [
            "open_naver_shopping",
            "close_popup",
            "search_product",
            "wait_results",
            "sort_by_popular",
            "extract_products",
            "scroll_for_more",
            "extract_more",
            "sort_by_price",
            "extract_price_sorted",
            "loop_pages",
        ]
        actual_ids = [s.step_id for s in steps]
        assert actual_ids == expected_ids

    def test_naver_workflow_verify_conditions(self) -> None:
        """Steps with verify conditions parse correctly."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        steps = parse_workflow(path)
        steps_by_id = {s.step_id: s for s in steps}

        # search_product has url_contains verify.
        sp = steps_by_id["search_product"]
        assert sp.verify_condition is not None
        assert sp.verify_condition.type == "url_contains"
        assert sp.verify_condition.value == "query="

        # sort_by_price has url_contains verify.
        sbp = steps_by_id["sort_by_price"]
        assert sbp.verify_condition is not None
        assert sbp.verify_condition.type == "url_contains"
        assert sbp.verify_condition.value == "sort=price"

        # loop_pages has url_changed verify.
        lp = steps_by_id["loop_pages"]
        assert lp.verify_condition is not None
        assert lp.verify_condition.type == "url_changed"

    def test_naver_workflow_node_types(self) -> None:
        """Steps have correct node types."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        steps = parse_workflow(path)
        steps_by_id = {s.step_id: s for s in steps}

        assert steps_by_id["open_naver_shopping"].node_type == "action"
        assert steps_by_id["wait_results"].node_type == "wait"
        assert steps_by_id["extract_products"].node_type == "extract"
        assert steps_by_id["loop_pages"].node_type == "loop"

    def test_naver_workflow_arguments(self) -> None:
        """Steps with arguments parse correctly."""
        path = _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
        steps = parse_workflow(path)
        steps_by_id = {s.step_id: s for s in steps}

        # open_naver_shopping has a URL argument.
        ons = steps_by_id["open_naver_shopping"]
        assert ons.arguments == ["https://shopping.naver.com"]

        # search_product has a search term argument.
        sp = steps_by_id["search_product"]
        assert "무선 이어폰" in sp.arguments

        # wait_results has network_idle argument.
        wr = steps_by_id["wait_results"]
        assert wr.arguments == ["network_idle"]


# ── 2. create_engine Returns Correct Types ───────────


class TestCreateEngine:
    """Test that create_engine wires modules correctly (mocked browser)."""

    async def test_create_engine_returns_tuple(self) -> None:
        """create_engine returns (Orchestrator, Executor, MemoryManager)."""
        with patch("scripts.run_poc.create_executor") as mock_create:
            from scripts.run_poc import create_engine

            mock_executor = AsyncMock()
            mock_page = AsyncMock()
            mock_executor.get_page = AsyncMock(return_value=mock_page)
            mock_create.return_value = mock_executor

            orch, executor, memory = await create_engine(headless=True)

            assert isinstance(orch, Orchestrator)
            # executor is our mock.
            assert executor is mock_executor
            # memory should be a MemoryManager.
            from src.learning.memory_manager import MemoryManager
            assert isinstance(memory, MemoryManager)

    async def test_create_engine_without_gemini_key(self) -> None:
        """Without GEMINI_API_KEY, planner should be None."""
        with patch("scripts.run_poc.create_executor") as mock_create, \
             patch.dict("os.environ", {}, clear=True):
            from scripts.run_poc import create_engine

            mock_executor = AsyncMock()
            mock_page = AsyncMock()
            mock_executor.get_page = AsyncMock(return_value=mock_page)
            mock_create.return_value = mock_executor

            orch, executor, memory = await create_engine(headless=True)

            # Planner should be None since no GEMINI_API_KEY.
            assert orch._planner is None


# ── 3. Iteration Loop ────────────────────────────────


class TestIterationLoop:
    """Test the multi-iteration execution loop."""

    async def test_single_iteration(self) -> None:
        """run_poc with iterations=1 returns 1 result."""
        with patch("scripts.run_poc.create_engine") as mock_ce:
            from scripts.run_poc import run_poc

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(
                return_value=[
                    StepResult(step_id="s1", success=True, method="R",
                               tokens_used=0, latency_ms=100.0, cost_usd=0.0),
                ]
            )
            mock_executor = AsyncMock()
            mock_memory = MagicMock()
            mock_ce.return_value = (mock_orch, mock_executor, mock_memory)

            workflow_path = (
                _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
            )
            results = await run_poc(workflow_path, headless=True, iterations=1)

            assert len(results) == 1
            assert results[0]["iteration"] == 1
            mock_executor.close.assert_awaited_once()

    async def test_multiple_iterations(self) -> None:
        """run_poc with iterations=3 returns 3 results."""
        with patch("scripts.run_poc.create_engine") as mock_ce:
            from scripts.run_poc import run_poc

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(
                return_value=[
                    StepResult(step_id="s1", success=True, method="R",
                               tokens_used=0, latency_ms=50.0, cost_usd=0.0),
                    StepResult(step_id="s2", success=True, method="R",
                               tokens_used=0, latency_ms=50.0, cost_usd=0.0),
                ]
            )
            mock_executor = AsyncMock()
            mock_memory = MagicMock()
            mock_ce.return_value = (mock_orch, mock_executor, mock_memory)

            workflow_path = (
                _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
            )
            results = await run_poc(workflow_path, headless=True, iterations=3)

            assert len(results) == 3
            assert results[0]["iteration"] == 1
            assert results[1]["iteration"] == 2
            assert results[2]["iteration"] == 3

    async def test_iteration_error_captured(self) -> None:
        """Errors during an iteration are captured, not raised."""
        with patch("scripts.run_poc.create_engine") as mock_ce:
            from scripts.run_poc import run_poc

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(side_effect=RuntimeError("Browser crashed"))
            mock_executor = AsyncMock()
            mock_memory = MagicMock()
            mock_ce.return_value = (mock_orch, mock_executor, mock_memory)

            workflow_path = (
                _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
            )
            results = await run_poc(workflow_path, headless=True, iterations=1)

            assert len(results) == 1
            assert "error" in results[0]
            assert "Browser crashed" in results[0]["error"]


# ── 4. Result JSON Structure ─────────────────────────


class TestResultStructure:
    """Test the structure of iteration result dictionaries."""

    async def test_success_result_structure(self) -> None:
        """Successful iteration has required keys."""
        with patch("scripts.run_poc.create_engine") as mock_ce:
            from scripts.run_poc import run_poc

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(
                return_value=[
                    StepResult(step_id="s1", success=True, method="R",
                               tokens_used=100, latency_ms=500.0, cost_usd=0.001),
                    StepResult(step_id="s2", success=False, method="L2",
                               tokens_used=200, latency_ms=1000.0, cost_usd=0.003,
                               failure_code=FailureCode.SELECTOR_NOT_FOUND),
                ]
            )
            mock_executor = AsyncMock()
            mock_memory = MagicMock()
            mock_ce.return_value = (mock_orch, mock_executor, mock_memory)

            workflow_path = (
                _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
            )
            results = await run_poc(workflow_path, headless=True, iterations=1)

            r = results[0]
            assert "iteration" in r
            assert "results" in r
            assert "total_steps" in r
            assert "successful_steps" in r
            assert "failed_steps" in r
            assert "total_tokens" in r
            assert "total_cost_usd" in r
            assert "total_latency_ms" in r
            assert "wall_time_s" in r
            assert "success_rate" in r
            assert "methods_used" in r

            # Check computed values.
            assert r["total_steps"] == 2
            assert r["successful_steps"] == 1
            assert r["failed_steps"] == 1
            assert r["total_tokens"] == 300
            assert r["total_cost_usd"] == 0.004
            assert r["success_rate"] == 0.5

    async def test_result_serializable_to_json(self) -> None:
        """Result dicts are JSON-serializable."""
        with patch("scripts.run_poc.create_engine") as mock_ce:
            from scripts.run_poc import run_poc

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(
                return_value=[
                    StepResult(step_id="s1", success=True, method="R",
                               tokens_used=0, latency_ms=100.0, cost_usd=0.0),
                ]
            )
            mock_executor = AsyncMock()
            mock_memory = MagicMock()
            mock_ce.return_value = (mock_orch, mock_executor, mock_memory)

            workflow_path = (
                _PROJECT_ROOT / "tests" / "fixtures" / "workflows" / "naver_shopping.yaml"
            )
            results = await run_poc(workflow_path, headless=True, iterations=1)

            # Should not raise.
            json_str = json.dumps(results, default=str)
            parsed = json.loads(json_str)
            assert isinstance(parsed, list)
            assert len(parsed) == 1


# ── 5. Summary Output Format ────────────────────────


class TestSummaryOutput:
    """Test the print_summary function."""

    def test_summary_with_results(self, capsys: pytest.CaptureFixture) -> None:
        """print_summary produces formatted output."""
        from scripts.run_poc import print_summary

        all_results = [
            {
                "iteration": 1,
                "success_rate": 0.8,
                "total_tokens": 100,
                "total_cost_usd": 0.001,
                "wall_time_s": 15.5,
            },
            {
                "iteration": 2,
                "success_rate": 0.9,
                "total_tokens": 50,
                "total_cost_usd": 0.0005,
                "wall_time_s": 12.0,
            },
        ]
        print_summary(all_results)

        captured = capsys.readouterr()
        assert "PoC Results Summary" in captured.out
        assert "Iterations: 2" in captured.out
        assert "Avg success rate" in captured.out

    def test_summary_with_empty_results(self, capsys: pytest.CaptureFixture) -> None:
        """print_summary handles empty results list."""
        from scripts.run_poc import print_summary

        print_summary([])

        captured = capsys.readouterr()
        assert "PoC Results Summary" in captured.out
        assert "No results to display" in captured.out

    def test_summary_with_error_iteration(self, capsys: pytest.CaptureFixture) -> None:
        """print_summary handles iterations with errors."""
        from scripts.run_poc import print_summary

        all_results = [
            {
                "iteration": 1,
                "error": "Browser crashed",
                "wall_time_s": 5.0,
            },
            {
                "iteration": 2,
                "success_rate": 1.0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "wall_time_s": 10.0,
            },
        ]
        print_summary(all_results)

        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        assert "Iterations: 2" in captured.out

    def test_summary_poc_criteria_check(self, capsys: pytest.CaptureFixture) -> None:
        """print_summary shows PoC criteria pass/fail."""
        from scripts.run_poc import print_summary

        all_results = [
            {
                "iteration": i + 1,
                "success_rate": 0.9,
                "total_tokens": 50 - i * 5,  # Decreasing
                "total_cost_usd": 0.005,
                "wall_time_s": 30.0,
            }
            for i in range(4)
        ]
        print_summary(all_results)

        captured = capsys.readouterr()
        assert "PoC Success Criteria" in captured.out
        assert "PASS" in captured.out or "FAIL" in captured.out


# ── 6. Benchmark Script Components ──────────────────


class TestBenchmarkComponents:
    """Test benchmark script helper functions."""

    def test_benchmark_poc_criteria_checker(self) -> None:
        """_check_poc_criteria evaluates criteria correctly."""
        from scripts.benchmark import _check_poc_criteria

        results = [
            {
                "success_rate": 0.9,
                "total_cost_usd": 0.005,
                "wall_time_s": 30.0,
                "llm_calls": 5,
                "rule_match_rate": 0.8,
            },
            {
                "success_rate": 0.85,
                "total_cost_usd": 0.003,
                "wall_time_s": 25.0,
                "llm_calls": 2,
                "rule_match_rate": 0.9,
            },
        ]

        criteria = _check_poc_criteria(results)

        assert criteria["success_rate_pass"] is True
        assert criteria["cost_pass"] is True
        assert criteria["time_pass"] is True

    def test_benchmark_summary_computation(self) -> None:
        """_compute_summary produces aggregate statistics."""
        from scripts.benchmark import _compute_summary

        results = [
            {
                "success_rate": 0.8,
                "total_tokens": 100,
                "total_cost_usd": 0.001,
                "wall_time_s": 20.0,
                "llm_calls": 3,
                "rule_match_rate": 0.6,
            },
            {
                "success_rate": 0.9,
                "total_tokens": 50,
                "total_cost_usd": 0.0005,
                "wall_time_s": 15.0,
                "llm_calls": 1,
                "rule_match_rate": 0.8,
            },
        ]

        summary = _compute_summary(results, iterations=2)

        assert summary["total_iterations"] == 2
        assert summary["successful_iterations"] == 2
        assert summary["avg_success_rate"] == pytest.approx(0.85)
        assert summary["avg_tokens"] == pytest.approx(75.0)
        assert summary["total_tokens"] == 150
        assert summary["avg_cost_usd"] == pytest.approx(0.00075)

    def test_benchmark_report_prints(self, capsys: pytest.CaptureFixture) -> None:
        """print_benchmark_report produces formatted output."""
        from scripts.benchmark import print_benchmark_report

        results = {
            "summary": {
                "workflow": "test.yaml",
                "total_iterations": 2,
                "successful_iterations": 2,
                "failed_iterations": 0,
                "avg_success_rate": 0.85,
                "avg_tokens": 75.0,
                "total_tokens": 150,
                "avg_cost_usd": 0.00075,
                "total_cost_usd": 0.0015,
                "avg_wall_time_s": 17.5,
                "avg_llm_calls": 2.0,
                "avg_rule_match_rate": 0.7,
                "overall_wall_time_s": 35.0,
                "poc_criteria": {
                    "success_rate_pass": True,
                    "success_rate_actual": 0.85,
                    "cost_pass": True,
                    "cost_actual_usd": 0.00075,
                    "time_pass": True,
                    "time_actual_s": 17.5,
                    "all_pass": True,
                },
            },
            "iterations": [
                {
                    "iteration": 1,
                    "success_rate": 0.8,
                    "total_tokens": 100,
                    "total_cost_usd": 0.001,
                    "wall_time_s": 20.0,
                    "llm_calls": 3,
                    "rule_match_rate": 0.6,
                },
                {
                    "iteration": 2,
                    "success_rate": 0.9,
                    "total_tokens": 50,
                    "total_cost_usd": 0.0005,
                    "wall_time_s": 15.0,
                    "llm_calls": 1,
                    "rule_match_rate": 0.8,
                },
            ],
        }

        print_benchmark_report(results)

        captured = capsys.readouterr()
        assert "Performance Benchmark Report" in captured.out
        assert "Iterations: 2" in captured.out
        assert "PASS" in captured.out


# ── 7. Settings File Validation ─────────────────────


class TestSettingsFile:
    """Test that the settings YAML is valid and complete."""

    def test_settings_file_exists(self) -> None:
        """config/settings.yaml exists."""
        path = _PROJECT_ROOT / "config" / "settings.yaml"
        assert path.exists()

    def test_settings_parses_as_yaml(self) -> None:
        """config/settings.yaml is valid YAML."""
        import yaml

        path = _PROJECT_ROOT / "config" / "settings.yaml"
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_settings_has_required_sections(self) -> None:
        """Settings contains required top-level keys."""
        import yaml

        path = _PROJECT_ROOT / "config" / "settings.yaml"
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        required_keys = ["engine", "browser", "llm", "vision", "learning", "memory"]
        for key in required_keys:
            assert key in data, f"Missing settings key: {key}"

    def test_settings_engine_values(self) -> None:
        """Engine settings have correct types and values."""
        import yaml

        path = _PROJECT_ROOT / "config" / "settings.yaml"
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        engine = data["engine"]
        assert engine["max_retries"] == 3
        assert engine["step_timeout_ms"] == 30000
        assert isinstance(engine["budget_limit_usd"], (int, float))
