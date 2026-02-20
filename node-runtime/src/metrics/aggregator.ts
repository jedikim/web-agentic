import type { RunMetrics } from './collector.js';

export interface SloCompliance {
  llmCallsPerRun: { target: number; actual: number; met: boolean };
  secondRunSuccessRate: { target: number; actual: number; met: boolean };
  postPatchRecoveryRate: { target: number; actual: number; met: boolean };
}

export interface AggregateMetrics {
  totalRuns: number;
  successRate: number;
  avgDurationMs: number;
  avgLlmCallsPerRun: number;
  avgTokensPerRun: { prompt: number; completion: number };
  patchRate: number;
  postPatchRecoveryRate: number;
  healingMemoryHitRate: number;
  avgCheckpointWaitMs: number;
  sloCompliance: SloCompliance;
  fallbackLadderDistribution: Record<string, number>;
  byFlow: Record<string, { runs: number; successRate: number; avgDuration: number }>;
}

export class MetricsAggregator {
  aggregate(metrics: RunMetrics[]): AggregateMetrics {
    if (metrics.length === 0) {
      return this.emptyAggregate();
    }

    const totalRuns = metrics.length;
    const successCount = metrics.filter((m) => m.success).length;
    const successRate = successCount / totalRuns;

    const avgDurationMs =
      metrics.reduce((sum, m) => sum + m.durationMs, 0) / totalRuns;

    const avgLlmCallsPerRun =
      metrics.reduce((sum, m) => sum + m.llmCalls, 0) / totalRuns;

    const avgTokensPerRun = {
      prompt: metrics.reduce((sum, m) => sum + m.tokenUsage.prompt, 0) / totalRuns,
      completion: metrics.reduce((sum, m) => sum + m.tokenUsage.completion, 0) / totalRuns,
    };

    const totalPatches = metrics.reduce((sum, m) => sum + m.patchCount, 0);
    const patchRate = totalPatches / totalRuns;

    const runsWithPatches = metrics.filter((m) => m.patchCount > 0);
    const postPatchRecoveryRate =
      runsWithPatches.length > 0
        ? runsWithPatches.reduce((sum, m) => sum + m.patchSuccessRate, 0) / runsWithPatches.length
        : 0;

    const totalHealingAttempts = metrics.reduce(
      (sum, m) => sum + m.healingMemoryHits + m.healingMemoryMisses,
      0,
    );
    const healingMemoryHitRate =
      totalHealingAttempts > 0
        ? metrics.reduce((sum, m) => sum + m.healingMemoryHits, 0) / totalHealingAttempts
        : 0;

    const avgCheckpointWaitMs =
      metrics.reduce((sum, m) => sum + m.checkpointWaitMs, 0) / totalRuns;

    // SLO: 2nd run success rate - runs after the first per flow
    const secondRunSuccessRate = this.computeSecondRunSuccessRate(metrics);

    const sloCompliance: SloCompliance = {
      llmCallsPerRun: {
        target: 0.2,
        actual: avgLlmCallsPerRun,
        met: avgLlmCallsPerRun <= 0.2,
      },
      secondRunSuccessRate: {
        target: 0.95,
        actual: secondRunSuccessRate,
        met: secondRunSuccessRate >= 0.95,
      },
      postPatchRecoveryRate: {
        target: 0.8,
        actual: postPatchRecoveryRate,
        met: postPatchRecoveryRate >= 0.8,
      },
    };

    const fallbackLadderDistribution = this.mergeFallbackUsage(metrics);

    const byFlow = this.computeByFlow(metrics);

    return {
      totalRuns,
      successRate,
      avgDurationMs,
      avgLlmCallsPerRun,
      avgTokensPerRun,
      patchRate,
      postPatchRecoveryRate,
      healingMemoryHitRate,
      avgCheckpointWaitMs,
      sloCompliance,
      fallbackLadderDistribution,
      byFlow,
    };
  }

  aggregateByFlow(metrics: RunMetrics[]): Record<string, AggregateMetrics> {
    const byFlow: Record<string, RunMetrics[]> = {};
    for (const m of metrics) {
      if (!byFlow[m.flow]) byFlow[m.flow] = [];
      byFlow[m.flow].push(m);
    }

    const result: Record<string, AggregateMetrics> = {};
    for (const [flow, flowMetrics] of Object.entries(byFlow)) {
      result[flow] = this.aggregate(flowMetrics);
    }
    return result;
  }

  private computeSecondRunSuccessRate(metrics: RunMetrics[]): number {
    const flowFirstRun = new Map<string, string>();
    const secondRuns: RunMetrics[] = [];

    // Sort by startedAt to determine order
    const sorted = [...metrics].sort(
      (a, b) => new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime(),
    );

    for (const m of sorted) {
      if (!flowFirstRun.has(m.flow)) {
        flowFirstRun.set(m.flow, m.runId);
      } else {
        secondRuns.push(m);
      }
    }

    if (secondRuns.length === 0) return 1; // No second runs yet, treat as compliant
    return secondRuns.filter((m) => m.success).length / secondRuns.length;
  }

  private mergeFallbackUsage(metrics: RunMetrics[]): Record<string, number> {
    const merged: Record<string, number> = {};
    for (const m of metrics) {
      for (const [method, count] of Object.entries(m.fallbackLadderUsage)) {
        merged[method] = (merged[method] ?? 0) + count;
      }
    }
    return merged;
  }

  private computeByFlow(
    metrics: RunMetrics[],
  ): Record<string, { runs: number; successRate: number; avgDuration: number }> {
    const byFlow: Record<string, RunMetrics[]> = {};
    for (const m of metrics) {
      if (!byFlow[m.flow]) byFlow[m.flow] = [];
      byFlow[m.flow].push(m);
    }

    const result: Record<string, { runs: number; successRate: number; avgDuration: number }> = {};
    for (const [flow, flowMetrics] of Object.entries(byFlow)) {
      const runs = flowMetrics.length;
      const successRate = flowMetrics.filter((m) => m.success).length / runs;
      const avgDuration = flowMetrics.reduce((sum, m) => sum + m.durationMs, 0) / runs;
      result[flow] = { runs, successRate, avgDuration };
    }
    return result;
  }

  private emptyAggregate(): AggregateMetrics {
    return {
      totalRuns: 0,
      successRate: 0,
      avgDurationMs: 0,
      avgLlmCallsPerRun: 0,
      avgTokensPerRun: { prompt: 0, completion: 0 },
      patchRate: 0,
      postPatchRecoveryRate: 0,
      healingMemoryHitRate: 0,
      avgCheckpointWaitMs: 0,
      sloCompliance: {
        llmCallsPerRun: { target: 0.2, actual: 0, met: true },
        secondRunSuccessRate: { target: 0.95, actual: 0, met: true },
        postPatchRecoveryRate: { target: 0.8, actual: 0, met: true },
      },
      fallbackLadderDistribution: {},
      byFlow: {},
    };
  }
}
