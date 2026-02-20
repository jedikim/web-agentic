import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { RegressionRunner } from '../../src/testing/regression-runner.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';
import type { StructuredTraceBundle } from '../../src/logging/trace-bundler.js';
import { writeFile, mkdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

function makeMockEngine(overrides?: Partial<BrowserEngine>): BrowserEngine {
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    act: vi.fn().mockResolvedValue(true),
    observe: vi.fn().mockResolvedValue([]),
    extract: vi.fn().mockResolvedValue({}),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('fake-png')),
    currentUrl: vi.fn().mockResolvedValue('https://example.com'),
    currentTitle: vi.fn().mockResolvedValue('Example'),
    ...overrides,
  };
}

function makeTraceBundle(
  flow: string,
  version: string,
  steps: StructuredTraceBundle['steps'] = [],
): StructuredTraceBundle {
  return {
    runId: `run-${randomUUID()}`,
    flow,
    version,
    timestamp: '2026-01-01T00:00:00Z',
    steps,
    metadata: {
      totalSteps: steps.length,
      passedSteps: steps.filter((s) => s.result.ok).length,
      failedSteps: steps.filter((s) => !s.result.ok).length,
      recoveredSteps: 0,
      llmCalls: 0,
      patchesApplied: 0,
    },
  };
}

describe('RegressionRunner', () => {
  let tracesDir: string;
  let runner: RegressionRunner;

  beforeEach(async () => {
    tracesDir = join(tmpdir(), `regression-runner-test-${randomUUID()}`);
    await mkdir(tracesDir, { recursive: true });
    runner = new RegressionRunner();
  });

  afterEach(async () => {
    await rm(tracesDir, { recursive: true, force: true });
  });

  describe('runSingle', () => {
    it('returns pass for a trace where all steps match', async () => {
      const engine = makeMockEngine();
      const trace = makeTraceBundle('booking', 'v001', [
        {
          stepId: 's1',
          op: 'goto',
          result: { stepId: 's1', ok: true, data: { url: 'https://example.com' } },
          durationMs: 100,
        },
        {
          stepId: 's2',
          op: 'checkpoint',
          result: { stepId: 's2', ok: true },
          durationMs: 10,
        },
      ]);

      const tracePath = join(tracesDir, 'booking-v001.json');
      await writeFile(tracePath, JSON.stringify(trace));

      const result = await runner.runSingle(tracePath, engine);

      expect(result.status).toBe('pass');
      expect(result.flow).toBe('booking');
      expect(result.version).toBe('v001');
      expect(result.replay.overallMatch).toBe(true);
    });

    it('returns fail when replay diverges', async () => {
      const engine = makeMockEngine({
        act: vi.fn().mockResolvedValue(false),
      });
      const trace = makeTraceBundle('login', 'v001', [
        {
          stepId: 's1',
          op: 'act_cached',
          targetKey: 'login.submit',
          result: {
            stepId: 's1',
            ok: true,
            data: { action: { selector: '#btn', description: 'btn', method: 'click' } },
          },
          durationMs: 200,
        },
      ]);

      const tracePath = join(tracesDir, 'login-v001.json');
      await writeFile(tracePath, JSON.stringify(trace));

      const result = await runner.runSingle(tracePath, engine);

      expect(result.status).toBe('fail');
      expect(result.replay.divergedSteps).toBe(1);
    });

    it('returns error for invalid trace file', async () => {
      const engine = makeMockEngine();
      const tracePath = join(tracesDir, 'invalid.json');
      await writeFile(tracePath, 'not valid json{{{');

      const result = await runner.runSingle(tracePath, engine);

      expect(result.status).toBe('error');
      expect(result.errorMessage).toBeDefined();
    });
  });

  describe('runAll', () => {
    it('runs all trace files in a directory', async () => {
      const engine = makeMockEngine();
      const trace1 = makeTraceBundle('booking', 'v001', [
        {
          stepId: 's1',
          op: 'checkpoint',
          result: { stepId: 's1', ok: true },
          durationMs: 10,
        },
      ]);
      const trace2 = makeTraceBundle('login', 'v002', [
        {
          stepId: 's1',
          op: 'checkpoint',
          result: { stepId: 's1', ok: true },
          durationMs: 10,
        },
      ]);

      await writeFile(join(tracesDir, 'booking.json'), JSON.stringify(trace1));
      await writeFile(join(tracesDir, 'login.json'), JSON.stringify(trace2));

      const report = await runner.runAll(tracesDir, engine);

      expect(report.totalTraces).toBe(2);
      expect(report.passed).toBe(2);
      expect(report.failed).toBe(0);
      expect(report.errors).toBe(0);
    });

    it('ignores non-json files', async () => {
      const engine = makeMockEngine();
      await writeFile(join(tracesDir, 'readme.txt'), 'not a trace');
      await writeFile(join(tracesDir, 'screenshot.png'), Buffer.from('fake'));

      const report = await runner.runAll(tracesDir, engine);
      expect(report.totalTraces).toBe(0);
    });

    it('reports mixed results correctly', async () => {
      const engine = makeMockEngine({
        act: vi.fn().mockResolvedValue(false),
      });

      // This one will pass (only checkpoint, no act)
      const passingTrace = makeTraceBundle('booking', 'v001', [
        {
          stepId: 's1',
          op: 'checkpoint',
          result: { stepId: 's1', ok: true },
          durationMs: 10,
        },
      ]);
      // This one will fail (act returns false)
      const failingTrace = makeTraceBundle('login', 'v001', [
        {
          stepId: 's1',
          op: 'act_cached',
          result: {
            stepId: 's1',
            ok: true,
            data: { action: { selector: '#btn', description: 'btn', method: 'click' } },
          },
          durationMs: 200,
        },
      ]);

      await writeFile(join(tracesDir, 'booking.json'), JSON.stringify(passingTrace));
      await writeFile(join(tracesDir, 'login.json'), JSON.stringify(failingTrace));

      const report = await runner.runAll(tracesDir, engine);

      expect(report.totalTraces).toBe(2);
      expect(report.passed).toBe(1);
      expect(report.failed).toBe(1);
    });
  });

  describe('generateReport', () => {
    it('generates a markdown report with all sections', () => {
      const results = [
        {
          tracePath: '/traces/booking.json',
          flow: 'booking',
          version: 'v001',
          replay: {
            originalRunId: 'run-1',
            replayRunId: 'replay-1',
            totalSteps: 3,
            matchedSteps: 3,
            divergedSteps: 0,
            divergences: [],
            overallMatch: true,
          },
          status: 'pass' as const,
        },
        {
          tracePath: '/traces/login.json',
          flow: 'login',
          version: 'v002',
          replay: {
            originalRunId: 'run-2',
            replayRunId: 'replay-2',
            totalSteps: 2,
            matchedSteps: 1,
            divergedSteps: 1,
            divergences: [
              {
                stepId: 's2',
                original: { ok: true },
                replayed: { ok: false },
                reason: 'Step "s2" passed originally but failed on replay',
              },
            ],
            overallMatch: false,
          },
          status: 'fail' as const,
        },
      ];

      const report = runner.generateReport(results);

      expect(report).toContain('# Regression Test Report');
      expect(report).toContain('**Total**: 2');
      expect(report).toContain('**Passed**: 1');
      expect(report).toContain('**Failed**: 1');
      expect(report).toContain('## Failures & Errors');
      expect(report).toContain('login');
      expect(report).toContain('Step `s2`');
      expect(report).toContain('## Passed');
      expect(report).toContain('booking');
    });

    it('generates report for all-pass results', () => {
      const results = [
        {
          tracePath: '/traces/booking.json',
          flow: 'booking',
          version: 'v001',
          replay: {
            originalRunId: 'run-1',
            replayRunId: 'replay-1',
            totalSteps: 5,
            matchedSteps: 5,
            divergedSteps: 0,
            divergences: [],
            overallMatch: true,
          },
          status: 'pass' as const,
        },
      ];

      const report = runner.generateReport(results);

      expect(report).toContain('**Total**: 1');
      expect(report).toContain('**Passed**: 1');
      expect(report).toContain('**Failed**: 0');
      expect(report).not.toContain('## Failures & Errors');
    });

    it('includes error messages for errored traces', () => {
      const results = [
        {
          tracePath: '/traces/broken.json',
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
          status: 'error' as const,
          errorMessage: 'File not found',
        },
      ];

      const report = runner.generateReport(results);
      expect(report).toContain('**Error**: File not found');
    });
  });
});
