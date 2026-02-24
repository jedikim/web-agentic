"""Tests for src.ops.metrics_dashboard — MetricsDashboard + MetricsSummary."""
from __future__ import annotations

import pytest

from src.ops.metrics_dashboard import MetricsDashboard, MetricsSummary, RunMetricInput


class TestEmptySummary:
    def test_empty_summary_returns_zeros(self) -> None:
        dash = MetricsDashboard()
        s = dash.summary()
        assert s == MetricsSummary(
            total_runs=0,
            avg_latency_ms=0.0,
            total_cost_usd=0.0,
            failure_rate=0.0,
            llm_calls_per_run=0.0,
        )


class TestSingleRecord:
    def test_single_record_summary(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(
            RunMetricInput(duration_ms=200.0, llm_calls=5, cost_usd=0.02, status="pass")
        )
        s = dash.summary()
        assert s.total_runs == 1
        assert s.avg_latency_ms == pytest.approx(200.0)
        assert s.total_cost_usd == pytest.approx(0.02)
        assert s.failure_rate == pytest.approx(0.0)
        assert s.llm_calls_per_run == pytest.approx(5.0)


class TestMultipleRecords:
    def test_multiple_records_summary(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=100, llm_calls=2, cost_usd=0.01, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=300, llm_calls=4, cost_usd=0.03, status="pass"))
        s = dash.summary()
        assert s.total_runs == 2
        assert s.avg_latency_ms == pytest.approx(200.0)
        assert s.total_cost_usd == pytest.approx(0.04)
        assert s.failure_rate == pytest.approx(0.0)
        assert s.llm_calls_per_run == pytest.approx(3.0)


class TestFailureRate:
    def test_failure_rate_calculation(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=100, llm_calls=1, cost_usd=0.01, status="fail"))
        dash.record_run(RunMetricInput(duration_ms=100, llm_calls=1, cost_usd=0.01, status="fail"))
        s = dash.summary()
        assert s.failure_rate == pytest.approx(1.0)


class TestLlmCallsPerRun:
    def test_llm_calls_per_run(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=50, llm_calls=10, cost_usd=0.005, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=50, llm_calls=20, cost_usd=0.005, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=50, llm_calls=30, cost_usd=0.005, status="pass"))
        s = dash.summary()
        assert s.llm_calls_per_run == pytest.approx(20.0)


class TestReset:
    def test_reset_clears_records(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=100, llm_calls=2, cost_usd=0.01, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=200, llm_calls=3, cost_usd=0.02, status="fail"))
        assert dash.summary().total_runs == 2
        dash.reset()
        s = dash.summary()
        assert s.total_runs == 0
        assert s.avg_latency_ms == 0.0
        assert s.total_cost_usd == 0.0


class TestMixedPassFail:
    def test_mixed_pass_fail(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=100, llm_calls=1, cost_usd=0.01, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=200, llm_calls=2, cost_usd=0.02, status="fail"))
        dash.record_run(RunMetricInput(duration_ms=300, llm_calls=3, cost_usd=0.03, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=400, llm_calls=4, cost_usd=0.04, status="fail"))
        s = dash.summary()
        assert s.total_runs == 4
        assert s.avg_latency_ms == pytest.approx(250.0)
        assert s.total_cost_usd == pytest.approx(0.10)
        assert s.failure_rate == pytest.approx(0.5)
        assert s.llm_calls_per_run == pytest.approx(2.5)


class TestZeroCostRuns:
    def test_zero_cost_runs(self) -> None:
        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=50, llm_calls=0, cost_usd=0.0, status="pass"))
        dash.record_run(RunMetricInput(duration_ms=150, llm_calls=0, cost_usd=0.0, status="pass"))
        s = dash.summary()
        assert s.total_runs == 2
        assert s.total_cost_usd == pytest.approx(0.0)
        assert s.llm_calls_per_run == pytest.approx(0.0)
        assert s.avg_latency_ms == pytest.approx(100.0)
