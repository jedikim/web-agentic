import { describe, it, expect } from 'vitest';
import { MetricsReporter } from '../../src/metrics/reporter.js';
import type { AggregateMetrics } from '../../src/metrics/aggregator.js';
import type { RunMetrics } from '../../src/metrics/collector.js';

function makeAggregate(overrides: Partial<AggregateMetrics> = {}): AggregateMetrics {
  return {
    totalRuns: 10,
    successRate: 0.9,
    avgDurationMs: 45000,
    avgLlmCallsPerRun: 0.1,
    avgTokensPerRun: { prompt: 120, completion: 40 },
    patchRate: 0.3,
    postPatchRecoveryRate: 0.85,
    healingMemoryHitRate: 0.7,
    avgCheckpointWaitMs: 3000,
    sloCompliance: {
      llmCallsPerRun: { target: 0.2, actual: 0.1, met: true },
      secondRunSuccessRate: { target: 0.95, actual: 0.98, met: true },
      postPatchRecoveryRate: { target: 0.8, actual: 0.85, met: true },
    },
    fallbackLadderDistribution: {
      observe_refresh: 5,
      healing_memory: 3,
      authoring_patch: 1,
    },
    byFlow: {
      booking: { runs: 6, successRate: 0.833, avgDuration: 50000 },
      login: { runs: 4, successRate: 1.0, avgDuration: 37500 },
    },
    ...overrides,
  };
}

function makeRunMetrics(overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    runId: 'run-42',
    flow: 'booking_flow',
    version: 'v003',
    startedAt: '2026-02-20T10:00:00Z',
    completedAt: '2026-02-20T10:00:45Z',
    success: true,
    durationMs: 45000,
    llmCalls: 1,
    tokenUsage: { prompt: 150, completion: 30 },
    patchCount: 1,
    patchSuccessRate: 1.0,
    healingMemoryHits: 2,
    healingMemoryMisses: 1,
    checkpointWaitMs: 5000,
    stepResults: { total: 4, passed: 3, failed: 0, recovered: 1 },
    fallbackLadderUsage: { observe_refresh: 1 },
    ...overrides,
  };
}

describe('MetricsReporter', () => {
  const reporter = new MetricsReporter();

  describe('generateJSON', () => {
    it('produces valid JSON matching the aggregate structure', () => {
      const aggregate = makeAggregate();
      const json = reporter.generateJSON(aggregate);
      const parsed = JSON.parse(json);

      expect(parsed.totalRuns).toBe(10);
      expect(parsed.successRate).toBe(0.9);
      expect(parsed.sloCompliance.llmCallsPerRun.met).toBe(true);
    });

    it('is formatted with indentation', () => {
      const json = reporter.generateJSON(makeAggregate());
      expect(json).toContain('\n');
      expect(json).toContain('  ');
    });
  });

  describe('generateMarkdown', () => {
    it('includes dashboard title', () => {
      const md = reporter.generateMarkdown(makeAggregate());
      expect(md).toContain('# Metrics Dashboard');
    });

    it('includes summary table with key metrics', () => {
      const md = reporter.generateMarkdown(makeAggregate());
      expect(md).toContain('Total Runs | 10');
      expect(md).toContain('90.0%');
    });

    it('includes SLO compliance section with PASS/FAIL indicators', () => {
      const md = reporter.generateMarkdown(makeAggregate());
      expect(md).toContain('## SLO Compliance');
      expect(md).toContain('PASS');
    });

    it('shows FAIL for non-compliant SLOs', () => {
      const aggregate = makeAggregate({
        sloCompliance: {
          llmCallsPerRun: { target: 0.2, actual: 0.5, met: false },
          secondRunSuccessRate: { target: 0.95, actual: 0.8, met: false },
          postPatchRecoveryRate: { target: 0.8, actual: 0.6, met: false },
        },
      });
      const md = reporter.generateMarkdown(aggregate);
      expect(md).toContain('FAIL');
    });

    it('includes fallback ladder distribution', () => {
      const md = reporter.generateMarkdown(makeAggregate());
      expect(md).toContain('## Fallback Ladder Usage');
      expect(md).toContain('observe_refresh');
      expect(md).toContain('healing_memory');
    });

    it('includes per-flow breakdown', () => {
      const md = reporter.generateMarkdown(makeAggregate());
      expect(md).toContain('## Per-Flow Breakdown');
      expect(md).toContain('booking');
      expect(md).toContain('login');
    });

    it('omits fallback section when no fallback usage', () => {
      const aggregate = makeAggregate({ fallbackLadderDistribution: {} });
      const md = reporter.generateMarkdown(aggregate);
      expect(md).not.toContain('## Fallback Ladder Usage');
    });

    it('omits per-flow section when no flows', () => {
      const aggregate = makeAggregate({ byFlow: {} });
      const md = reporter.generateMarkdown(aggregate);
      expect(md).not.toContain('## Per-Flow Breakdown');
    });
  });

  describe('generateRunReport', () => {
    it('includes run metadata', () => {
      const md = reporter.generateRunReport(makeRunMetrics());
      expect(md).toContain('# Run Report');
      expect(md).toContain('run-42');
      expect(md).toContain('booking_flow');
      expect(md).toContain('v003');
      expect(md).toContain('Success');
    });

    it('shows failure status', () => {
      const md = reporter.generateRunReport(makeRunMetrics({ success: false }));
      expect(md).toContain('Failure');
    });

    it('includes step counts', () => {
      const md = reporter.generateRunReport(makeRunMetrics());
      expect(md).toContain('Total: 4');
      expect(md).toContain('Passed: 3');
      expect(md).toContain('Recovered: 1');
    });

    it('includes LLM usage', () => {
      const md = reporter.generateRunReport(makeRunMetrics());
      expect(md).toContain('Calls: 1');
      expect(md).toContain('Prompt tokens: 150');
      expect(md).toContain('Completion tokens: 30');
    });

    it('includes recovery information', () => {
      const md = reporter.generateRunReport(makeRunMetrics());
      expect(md).toContain('Patches: 1');
      expect(md).toContain('2 hits');
      expect(md).toContain('1 misses');
    });

    it('includes fallback methods when present', () => {
      const md = reporter.generateRunReport(makeRunMetrics());
      expect(md).toContain('## Fallback Methods Used');
      expect(md).toContain('observe_refresh: 1');
    });

    it('omits fallback section when no fallback usage', () => {
      const md = reporter.generateRunReport(makeRunMetrics({ fallbackLadderUsage: {} }));
      expect(md).not.toContain('## Fallback Methods Used');
    });
  });
});
