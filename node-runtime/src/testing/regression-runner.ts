import { readdir } from 'node:fs/promises';
import { join } from 'node:path';
import type { BrowserEngine } from '../engines/browser-engine.js';
import { TraceReplayer } from './trace-replayer.js';
import type { ReplayResult } from './trace-replayer.js';

export interface RegressionResult {
  tracePath: string;
  flow: string;
  version: string;
  replay: ReplayResult;
  status: 'pass' | 'fail' | 'error';
  errorMessage?: string;
}

export interface RegressionReport {
  timestamp: string;
  totalTraces: number;
  passed: number;
  failed: number;
  errors: number;
  results: RegressionResult[];
}

/**
 * RegressionRunner runs trace archives as regression tests.
 * It replays each saved trace against a live BrowserEngine
 * and produces a report of pass/fail/diff for each.
 */
export class RegressionRunner {
  private replayer = new TraceReplayer();

  /**
   * Run all trace.json files found in the given directory as regression tests.
   */
  async runAll(tracesDir: string, engine: BrowserEngine): Promise<RegressionReport> {
    const files = await readdir(tracesDir);
    const traceFiles = files.filter((f) => f.endsWith('.json'));
    const results: RegressionResult[] = [];

    for (const file of traceFiles) {
      const tracePath = join(tracesDir, file);
      const result = await this.runSingle(tracePath, engine);
      results.push(result);
    }

    const passed = results.filter((r) => r.status === 'pass').length;
    const failed = results.filter((r) => r.status === 'fail').length;
    const errors = results.filter((r) => r.status === 'error').length;

    return {
      timestamp: new Date().toISOString(),
      totalTraces: results.length,
      passed,
      failed,
      errors,
      results,
    };
  }

  /**
   * Run a single trace file as a regression test.
   */
  async runSingle(tracePath: string, engine: BrowserEngine): Promise<RegressionResult> {
    try {
      const trace = await this.replayer.loadTrace(tracePath);
      const replay = await this.replayer.replay(trace, engine);

      return {
        tracePath,
        flow: trace.flow,
        version: trace.version,
        replay,
        status: replay.overallMatch ? 'pass' : 'fail',
      };
    } catch (error) {
      return {
        tracePath,
        flow: '',
        version: '',
        replay: {
          originalRunId: '',
          replayRunId: '',
          totalSteps: 0,
          matchedSteps: 0,
          divergedSteps: 0,
          divergences: [],
          overallMatch: false,
        },
        status: 'error',
        errorMessage: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Generate a Markdown report from regression results.
   */
  generateReport(results: RegressionResult[]): string {
    const passed = results.filter((r) => r.status === 'pass').length;
    const failed = results.filter((r) => r.status === 'fail').length;
    const errors = results.filter((r) => r.status === 'error').length;
    const total = results.length;

    const lines: string[] = [
      '# Regression Test Report',
      '',
      `- **Total**: ${total}`,
      `- **Passed**: ${passed}`,
      `- **Failed**: ${failed}`,
      `- **Errors**: ${errors}`,
      '',
    ];

    if (failed > 0 || errors > 0) {
      lines.push('## Failures & Errors', '');

      for (const result of results) {
        if (result.status === 'pass') continue;

        lines.push(`### ${result.flow || result.tracePath} (${result.version || 'unknown'})`);
        lines.push(`- **Status**: ${result.status}`);

        if (result.errorMessage) {
          lines.push(`- **Error**: ${result.errorMessage}`);
        }

        if (result.replay.divergences.length > 0) {
          lines.push('- **Divergences**:');
          for (const div of result.replay.divergences) {
            lines.push(`  - Step \`${div.stepId}\`: ${div.reason}`);
          }
        }
        lines.push('');
      }
    }

    if (passed > 0) {
      lines.push('## Passed', '');
      for (const result of results) {
        if (result.status !== 'pass') continue;
        lines.push(
          `- ${result.flow || result.tracePath} (${result.version || 'unknown'}): ${result.replay.matchedSteps}/${result.replay.totalSteps} steps matched`,
        );
      }
      lines.push('');
    }

    return lines.join('\n');
  }
}
