import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { TraceReplayer } from '../../src/testing/trace-replayer.js';
import type { StepDivergence } from '../../src/testing/trace-replayer.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';
import type { StructuredTraceBundle, TraceStep } from '../../src/logging/trace-bundler.js';
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

function makeTrace(steps: TraceStep[], overrides?: Partial<StructuredTraceBundle>): StructuredTraceBundle {
  return {
    runId: 'test-run',
    flow: 'test-flow',
    version: 'v001',
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
    ...overrides,
  };
}

function makeStep(overrides?: Partial<TraceStep>): TraceStep {
  return {
    stepId: 's1',
    op: 'goto',
    result: { stepId: 's1', ok: true },
    durationMs: 100,
    ...overrides,
  };
}

describe('TraceReplayer', () => {
  let replayer: TraceReplayer;
  let dir: string;

  beforeEach(async () => {
    replayer = new TraceReplayer();
    dir = join(tmpdir(), `trace-replayer-test-${randomUUID()}`);
    await mkdir(dir, { recursive: true });
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  describe('loadTrace', () => {
    it('loads a trace from a JSON file', async () => {
      const trace = makeTrace([makeStep()]);
      const tracePath = join(dir, 'trace.json');
      await writeFile(tracePath, JSON.stringify(trace));

      const loaded = await replayer.loadTrace(tracePath);
      expect(loaded.runId).toBe('test-run');
      expect(loaded.steps).toHaveLength(1);
    });
  });

  describe('replay', () => {
    it('replays all steps and returns matching result when all pass', async () => {
      const engine = makeMockEngine();
      const trace = makeTrace([
        makeStep({ stepId: 's1', op: 'goto', result: { stepId: 's1', ok: true, data: { url: 'https://example.com' } } }),
        makeStep({ stepId: 's2', op: 'checkpoint', result: { stepId: 's2', ok: true } }),
      ]);

      const result = await replayer.replay(trace, engine);

      expect(result.overallMatch).toBe(true);
      expect(result.totalSteps).toBe(2);
      expect(result.matchedSteps).toBe(2);
      expect(result.divergedSteps).toBe(0);
      expect(result.divergences).toHaveLength(0);
    });

    it('detects divergence when a step fails during replay', async () => {
      const engine = makeMockEngine({
        act: vi.fn().mockResolvedValue(false),
      });
      const trace = makeTrace([
        makeStep({
          stepId: 's1',
          op: 'act_cached',
          targetKey: 'login.submit',
          result: {
            stepId: 's1',
            ok: true,
            data: { action: { selector: '#btn', description: 'btn', method: 'click' } },
          },
        }),
      ]);

      const result = await replayer.replay(trace, engine);

      expect(result.overallMatch).toBe(false);
      expect(result.divergedSteps).toBe(1);
      expect(result.divergences[0].stepId).toBe('s1');
      expect(result.divergences[0].reason).toContain('passed originally but failed on replay');
    });

    it('handles goto steps correctly', async () => {
      const engine = makeMockEngine();
      const trace = makeTrace([
        makeStep({
          stepId: 's1',
          op: 'goto',
          result: { stepId: 's1', ok: true, data: { url: 'https://example.com' } },
        }),
      ]);

      const result = await replayer.replay(trace, engine);

      expect(result.overallMatch).toBe(true);
      expect(engine.goto).toHaveBeenCalledWith('https://example.com');
    });

    it('handles extract steps correctly', async () => {
      const engine = makeMockEngine({
        extract: vi.fn().mockResolvedValue({ items: ['a', 'b'] }),
      });
      const trace = makeTrace([
        makeStep({
          stepId: 's1',
          op: 'extract',
          result: { stepId: 's1', ok: true, data: { schema: { type: 'array' } } },
        }),
      ]);

      const result = await replayer.replay(trace, engine);
      expect(result.overallMatch).toBe(true);
    });

    it('auto-passes non-browser steps (checkpoint, choose, wait)', async () => {
      const engine = makeMockEngine();
      const trace = makeTrace([
        makeStep({ stepId: 's1', op: 'checkpoint', result: { stepId: 's1', ok: true } }),
        makeStep({ stepId: 's2', op: 'choose', result: { stepId: 's2', ok: true } }),
        makeStep({ stepId: 's3', op: 'wait', result: { stepId: 's3', ok: true } }),
      ]);

      const result = await replayer.replay(trace, engine);
      expect(result.overallMatch).toBe(true);
      expect(result.matchedSteps).toBe(3);
    });

    it('handles engine errors gracefully', async () => {
      const engine = makeMockEngine({
        goto: vi.fn().mockRejectedValue(new Error('Connection refused')),
      });
      const trace = makeTrace([
        makeStep({
          stepId: 's1',
          op: 'goto',
          result: { stepId: 's1', ok: true, data: { url: 'https://example.com' } },
        }),
      ]);

      const result = await replayer.replay(trace, engine);
      expect(result.overallMatch).toBe(false);
      expect(result.divergences[0].reason).toContain('passed originally but failed on replay');
    });
  });

  describe('compareStep', () => {
    it('returns null when both steps pass', () => {
      const original = makeStep({ result: { stepId: 's1', ok: true } });
      const replayed = { stepId: 's1', ok: true };

      const divergence = replayer.compareStep(original, replayed);
      expect(divergence).toBeNull();
    });

    it('returns null when both steps fail with same error type', () => {
      const original = makeStep({
        result: { stepId: 's1', ok: false, errorType: 'TargetNotFound' },
      });
      const replayed = { stepId: 's1', ok: false, errorType: 'TargetNotFound' as const };

      const divergence = replayer.compareStep(original, replayed);
      expect(divergence).toBeNull();
    });

    it('detects divergence when ok status differs (original pass, replay fail)', () => {
      const original = makeStep({ result: { stepId: 's1', ok: true } });
      const replayed = { stepId: 's1', ok: false, message: 'element not found' };

      const divergence = replayer.compareStep(original, replayed);
      expect(divergence).not.toBeNull();
      expect(divergence!.reason).toContain('passed originally but failed on replay');
    });

    it('detects divergence when ok status differs (original fail, replay pass)', () => {
      const original = makeStep({
        result: { stepId: 's1', ok: false, errorType: 'TargetNotFound' },
      });
      const replayed = { stepId: 's1', ok: true };

      const divergence = replayer.compareStep(original, replayed);
      expect(divergence).not.toBeNull();
      expect(divergence!.reason).toContain('failed originally but passed on replay');
    });

    it('detects divergence when both fail but error types differ', () => {
      const original = makeStep({
        result: { stepId: 's1', ok: false, errorType: 'TargetNotFound' },
      });
      const replayed = { stepId: 's1', ok: false, errorType: 'NotActionable' as const };

      const divergence = replayer.compareStep(original, replayed);
      expect(divergence).not.toBeNull();
      expect(divergence!.reason).toContain('error type changed');
    });
  });
});
