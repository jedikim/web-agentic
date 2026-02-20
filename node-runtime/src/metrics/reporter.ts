import type { AggregateMetrics } from './aggregator.js';
import type { RunMetrics } from './collector.js';

export class MetricsReporter {
  generateJSON(aggregate: AggregateMetrics): string {
    return JSON.stringify(aggregate, null, 2);
  }

  generateMarkdown(aggregate: AggregateMetrics): string {
    const lines: string[] = [];

    lines.push('# Metrics Dashboard');
    lines.push('');

    // Summary table
    lines.push('## Summary');
    lines.push('');
    lines.push('| Metric | Value |');
    lines.push('|--------|-------|');
    lines.push(`| Total Runs | ${aggregate.totalRuns} |`);
    lines.push(`| Success Rate | ${formatPercent(aggregate.successRate)} |`);
    lines.push(`| Avg Duration | ${formatDuration(aggregate.avgDurationMs)} |`);
    lines.push(`| Avg LLM Calls/Run | ${aggregate.avgLlmCallsPerRun.toFixed(2)} |`);
    lines.push(`| Avg Tokens/Run (prompt) | ${Math.round(aggregate.avgTokensPerRun.prompt)} |`);
    lines.push(`| Avg Tokens/Run (completion) | ${Math.round(aggregate.avgTokensPerRun.completion)} |`);
    lines.push(`| Patch Rate | ${aggregate.patchRate.toFixed(2)}/run |`);
    lines.push(`| Post-Patch Recovery Rate | ${formatPercent(aggregate.postPatchRecoveryRate)} |`);
    lines.push(`| Healing Memory Hit Rate | ${formatPercent(aggregate.healingMemoryHitRate)} |`);
    lines.push(`| Avg Checkpoint Wait | ${formatDuration(aggregate.avgCheckpointWaitMs)} |`);
    lines.push('');

    // SLO compliance
    lines.push('## SLO Compliance');
    lines.push('');
    lines.push('| SLO | Target | Actual | Status |');
    lines.push('|-----|--------|--------|--------|');

    const slo = aggregate.sloCompliance;
    lines.push(
      `| LLM Calls/Run | <= ${slo.llmCallsPerRun.target} | ${slo.llmCallsPerRun.actual.toFixed(2)} | ${slo.llmCallsPerRun.met ? 'PASS' : 'FAIL'} |`,
    );
    lines.push(
      `| 2nd Run Success Rate | >= ${formatPercent(slo.secondRunSuccessRate.target)} | ${formatPercent(slo.secondRunSuccessRate.actual)} | ${slo.secondRunSuccessRate.met ? 'PASS' : 'FAIL'} |`,
    );
    lines.push(
      `| Post-Patch Recovery | >= ${formatPercent(slo.postPatchRecoveryRate.target)} | ${formatPercent(slo.postPatchRecoveryRate.actual)} | ${slo.postPatchRecoveryRate.met ? 'PASS' : 'FAIL'} |`,
    );
    lines.push('');

    // Fallback ladder usage
    const fallbackEntries = Object.entries(aggregate.fallbackLadderDistribution);
    if (fallbackEntries.length > 0) {
      lines.push('## Fallback Ladder Usage');
      lines.push('');
      lines.push('| Method | Count |');
      lines.push('|--------|-------|');
      const sorted = fallbackEntries.sort((a, b) => b[1] - a[1]);
      for (const [method, count] of sorted) {
        lines.push(`| ${method} | ${count} |`);
      }
      lines.push('');
    }

    // Per-flow breakdown
    const flowEntries = Object.entries(aggregate.byFlow);
    if (flowEntries.length > 0) {
      lines.push('## Per-Flow Breakdown');
      lines.push('');
      lines.push('| Flow | Runs | Success Rate | Avg Duration |');
      lines.push('|------|------|-------------|--------------|');
      for (const [flow, stats] of flowEntries) {
        lines.push(
          `| ${flow} | ${stats.runs} | ${formatPercent(stats.successRate)} | ${formatDuration(stats.avgDuration)} |`,
        );
      }
      lines.push('');
    }

    return lines.join('\n');
  }

  generateRunReport(metrics: RunMetrics): string {
    const lines: string[] = [];

    lines.push('# Run Report');
    lines.push('');
    lines.push(`- **Run ID:** ${metrics.runId}`);
    lines.push(`- **Flow:** ${metrics.flow}`);
    lines.push(`- **Version:** ${metrics.version}`);
    lines.push(`- **Result:** ${metrics.success ? 'Success' : 'Failure'}`);
    lines.push(`- **Duration:** ${formatDuration(metrics.durationMs)}`);
    lines.push(`- **Started:** ${metrics.startedAt}`);
    lines.push(`- **Completed:** ${metrics.completedAt}`);
    lines.push('');

    lines.push('## Steps');
    lines.push('');
    lines.push(`- Total: ${metrics.stepResults.total}`);
    lines.push(`- Passed: ${metrics.stepResults.passed}`);
    lines.push(`- Failed: ${metrics.stepResults.failed}`);
    lines.push(`- Recovered: ${metrics.stepResults.recovered}`);
    lines.push('');

    lines.push('## LLM Usage');
    lines.push('');
    lines.push(`- Calls: ${metrics.llmCalls}`);
    lines.push(`- Prompt tokens: ${metrics.tokenUsage.prompt}`);
    lines.push(`- Completion tokens: ${metrics.tokenUsage.completion}`);
    lines.push('');

    lines.push('## Recovery');
    lines.push('');
    lines.push(`- Patches: ${metrics.patchCount} (success rate: ${formatPercent(metrics.patchSuccessRate)})`);
    lines.push(`- Healing memory: ${metrics.healingMemoryHits} hits, ${metrics.healingMemoryMisses} misses`);
    lines.push(`- Checkpoint wait: ${formatDuration(metrics.checkpointWaitMs)}`);

    const fallbackEntries = Object.entries(metrics.fallbackLadderUsage);
    if (fallbackEntries.length > 0) {
      lines.push('');
      lines.push('## Fallback Methods Used');
      lines.push('');
      for (const [method, count] of fallbackEntries) {
        lines.push(`- ${method}: ${count}`);
      }
    }

    lines.push('');
    return lines.join('\n');
  }
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
  }
  return `${seconds}s`;
}
