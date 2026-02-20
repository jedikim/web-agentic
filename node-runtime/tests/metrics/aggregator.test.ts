import { describe, it, expect } from 'vitest';
import { MetricsAggregator } from '../../src/metrics/aggregator.js';
import type { RunMetrics } from '../../src/metrics/collector.js';

function makeMetrics(overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    runId: 'run-1',
    flow: 'booking_flow',
    version: 'v001',
    startedAt: '2026-02-20T10:00:00Z',
    completedAt: '2026-02-20T10:01:00Z',
    success: true,
    durationMs: 60000,
    llmCalls: 0,
    tokenUsage: { prompt: 0, completion: 0 },
    patchCount: 0,
    patchSuccessRate: 0,
    healingMemoryHits: 0,
    healingMemoryMisses: 0,
    checkpointWaitMs: 0,
    stepResults: { total: 5, passed: 5, failed: 0, recovered: 0 },
    fallbackLadderUsage: {},
    ...overrides,
  };
}

describe('MetricsAggregator', () => {
  const aggregator = new MetricsAggregator();

  describe('aggregate', () => {
    it('returns empty aggregate for no metrics', () => {
      const result = aggregator.aggregate([]);
      expect(result.totalRuns).toBe(0);
      expect(result.successRate).toBe(0);
    });

    it('computes correct rates for a single successful run', () => {
      const metrics = [makeMetrics()];
      const result = aggregator.aggregate(metrics);

      expect(result.totalRuns).toBe(1);
      expect(result.successRate).toBe(1);
      expect(result.avgDurationMs).toBe(60000);
      expect(result.avgLlmCallsPerRun).toBe(0);
    });

    it('computes correct success rate for mixed results', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', success: true }),
        makeMetrics({ runId: 'r2', success: false }),
        makeMetrics({ runId: 'r3', success: true }),
        makeMetrics({ runId: 'r4', success: true }),
      ];
      const result = aggregator.aggregate(metrics);

      expect(result.totalRuns).toBe(4);
      expect(result.successRate).toBe(0.75);
    });

    it('averages duration and LLM calls', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', durationMs: 30000, llmCalls: 1 }),
        makeMetrics({ runId: 'r2', durationMs: 90000, llmCalls: 3 }),
      ];
      const result = aggregator.aggregate(metrics);

      expect(result.avgDurationMs).toBe(60000);
      expect(result.avgLlmCallsPerRun).toBe(2);
    });

    it('averages token usage', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', tokenUsage: { prompt: 100, completion: 50 } }),
        makeMetrics({ runId: 'r2', tokenUsage: { prompt: 200, completion: 150 } }),
      ];
      const result = aggregator.aggregate(metrics);

      expect(result.avgTokensPerRun.prompt).toBe(150);
      expect(result.avgTokensPerRun.completion).toBe(100);
    });

    it('computes patch rate', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', patchCount: 2 }),
        makeMetrics({ runId: 'r2', patchCount: 0 }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.patchRate).toBe(1); // 2 patches / 2 runs
    });

    it('computes post-patch recovery rate from runs with patches', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', patchCount: 2, patchSuccessRate: 1.0 }),
        makeMetrics({ runId: 'r2', patchCount: 1, patchSuccessRate: 0.5 }),
        makeMetrics({ runId: 'r3', patchCount: 0, patchSuccessRate: 0 }), // no patches, ignored
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.postPatchRecoveryRate).toBe(0.75); // (1.0 + 0.5) / 2
    });

    it('computes healing memory hit rate', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', healingMemoryHits: 3, healingMemoryMisses: 1 }),
        makeMetrics({ runId: 'r2', healingMemoryHits: 1, healingMemoryMisses: 1 }),
      ];
      const result = aggregator.aggregate(metrics);
      // Total: 4 hits, 2 misses = 4/6
      expect(result.healingMemoryHitRate).toBeCloseTo(4 / 6);
    });

    it('merges fallback ladder usage', () => {
      const metrics = [
        makeMetrics({
          runId: 'r1',
          fallbackLadderUsage: { observe_refresh: 2, healing_memory: 1 },
        }),
        makeMetrics({
          runId: 'r2',
          fallbackLadderUsage: { observe_refresh: 1, authoring_patch: 1 },
        }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.fallbackLadderDistribution).toEqual({
        observe_refresh: 3,
        healing_memory: 1,
        authoring_patch: 1,
      });
    });

    it('computes per-flow breakdown', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', flow: 'booking', durationMs: 30000, success: true }),
        makeMetrics({ runId: 'r2', flow: 'booking', durationMs: 50000, success: false }),
        makeMetrics({ runId: 'r3', flow: 'login', durationMs: 10000, success: true }),
      ];
      const result = aggregator.aggregate(metrics);

      expect(result.byFlow['booking']).toEqual({
        runs: 2,
        successRate: 0.5,
        avgDuration: 40000,
      });
      expect(result.byFlow['login']).toEqual({
        runs: 1,
        successRate: 1,
        avgDuration: 10000,
      });
    });
  });

  describe('SLO compliance', () => {
    it('marks LLM calls SLO as PASS when <= 0.2', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', llmCalls: 0 }),
        makeMetrics({ runId: 'r2', llmCalls: 0 }),
        makeMetrics({ runId: 'r3', llmCalls: 0 }),
        makeMetrics({ runId: 'r4', llmCalls: 0 }),
        makeMetrics({ runId: 'r5', llmCalls: 1 }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.sloCompliance.llmCallsPerRun.actual).toBe(0.2);
      expect(result.sloCompliance.llmCallsPerRun.met).toBe(true);
    });

    it('marks LLM calls SLO as FAIL when > 0.2', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', llmCalls: 1 }),
        makeMetrics({ runId: 'r2', llmCalls: 1 }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.sloCompliance.llmCallsPerRun.actual).toBe(1);
      expect(result.sloCompliance.llmCallsPerRun.met).toBe(false);
    });

    it('computes 2nd run success rate across flows', () => {
      const metrics = [
        makeMetrics({
          runId: 'r1',
          flow: 'booking',
          startedAt: '2026-02-20T10:00:00Z',
          success: true,
        }),
        makeMetrics({
          runId: 'r2',
          flow: 'booking',
          startedAt: '2026-02-20T11:00:00Z',
          success: true,
        }),
        makeMetrics({
          runId: 'r3',
          flow: 'login',
          startedAt: '2026-02-20T10:30:00Z',
          success: false,
        }),
        makeMetrics({
          runId: 'r4',
          flow: 'login',
          startedAt: '2026-02-20T11:30:00Z',
          success: true,
        }),
      ];
      const result = aggregator.aggregate(metrics);
      // Second runs: r2 (success), r4 (success) => 100%
      expect(result.sloCompliance.secondRunSuccessRate.actual).toBe(1);
      expect(result.sloCompliance.secondRunSuccessRate.met).toBe(true);
    });

    it('marks 2nd run SLO as FAIL when < 95%', () => {
      const metrics: RunMetrics[] = [];
      // Create 2 flows with 10 second runs each, where 1 fails
      for (let i = 0; i < 20; i++) {
        const flow = i < 10 ? 'flowA' : 'flowB';
        const hour = String(i).padStart(2, '0');
        metrics.push(
          makeMetrics({
            runId: `r${i}`,
            flow,
            startedAt: `2026-02-20T${hour}:00:00Z`,
            success: i !== 1 && i !== 3, // fail runs 1 and 3 (both are 2nd+ runs)
          }),
        );
      }
      const result = aggregator.aggregate(metrics);
      // 18 second+ runs, 2 failed => 16/18 = 88.9%
      expect(result.sloCompliance.secondRunSuccessRate.actual).toBeCloseTo(16 / 18);
      expect(result.sloCompliance.secondRunSuccessRate.met).toBe(false);
    });

    it('marks post-patch recovery SLO as PASS when >= 80%', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', patchCount: 1, patchSuccessRate: 1.0 }),
        makeMetrics({ runId: 'r2', patchCount: 1, patchSuccessRate: 0.8 }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.sloCompliance.postPatchRecoveryRate.actual).toBe(0.9);
      expect(result.sloCompliance.postPatchRecoveryRate.met).toBe(true);
    });

    it('marks post-patch recovery SLO as FAIL when < 80%', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', patchCount: 1, patchSuccessRate: 0.5 }),
        makeMetrics({ runId: 'r2', patchCount: 1, patchSuccessRate: 0.6 }),
      ];
      const result = aggregator.aggregate(metrics);
      expect(result.sloCompliance.postPatchRecoveryRate.actual).toBe(0.55);
      expect(result.sloCompliance.postPatchRecoveryRate.met).toBe(false);
    });
  });

  describe('aggregateByFlow', () => {
    it('groups metrics by flow and aggregates independently', () => {
      const metrics = [
        makeMetrics({ runId: 'r1', flow: 'booking', durationMs: 30000 }),
        makeMetrics({ runId: 'r2', flow: 'booking', durationMs: 50000 }),
        makeMetrics({ runId: 'r3', flow: 'login', durationMs: 10000, llmCalls: 1 }),
      ];
      const result = aggregator.aggregateByFlow(metrics);

      expect(Object.keys(result)).toEqual(['booking', 'login']);
      expect(result['booking'].totalRuns).toBe(2);
      expect(result['booking'].avgDurationMs).toBe(40000);
      expect(result['login'].totalRuns).toBe(1);
      expect(result['login'].avgLlmCallsPerRun).toBe(1);
    });
  });
});
