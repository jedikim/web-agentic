import { describe, it, expect, beforeEach } from 'vitest';
import { MetricsCollector } from '../../src/metrics/collector.js';
import type { StepResult } from '../../src/types/index.js';

describe('MetricsCollector', () => {
  let collector: MetricsCollector;

  beforeEach(() => {
    collector = new MetricsCollector();
  });

  describe('startRun + finalize', () => {
    it('produces metrics with correct run metadata', () => {
      collector.startRun('run-1', 'booking_flow', 'v001');
      const metrics = collector.finalize(true);

      expect(metrics.runId).toBe('run-1');
      expect(metrics.flow).toBe('booking_flow');
      expect(metrics.version).toBe('v001');
      expect(metrics.success).toBe(true);
      expect(metrics.startedAt).toBeDefined();
      expect(metrics.completedAt).toBeDefined();
      expect(metrics.durationMs).toBeGreaterThanOrEqual(0);
    });

    it('records failure when finalized with false', () => {
      collector.startRun('run-2', 'login_flow', 'v001');
      const metrics = collector.finalize(false);
      expect(metrics.success).toBe(false);
    });

    it('resets state between runs', () => {
      collector.startRun('run-1', 'flow1', 'v001');
      collector.recordLlmCall({ prompt: 100, completion: 50 });
      collector.finalize(true);

      collector.startRun('run-2', 'flow2', 'v002');
      const metrics = collector.finalize(true);

      expect(metrics.runId).toBe('run-2');
      expect(metrics.llmCalls).toBe(0);
      expect(metrics.tokenUsage.prompt).toBe(0);
    });
  });

  describe('recordStep', () => {
    it('counts passed steps', () => {
      collector.startRun('run-1', 'flow', 'v001');

      const ok: StepResult = { stepId: 's1', ok: true };
      collector.recordStep(ok);
      collector.recordStep({ stepId: 's2', ok: true });

      const metrics = collector.finalize(true);
      expect(metrics.stepResults.total).toBe(2);
      expect(metrics.stepResults.passed).toBe(2);
      expect(metrics.stepResults.failed).toBe(0);
      expect(metrics.stepResults.recovered).toBe(0);
    });

    it('counts failed steps', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordStep({ stepId: 's1', ok: false, errorType: 'TargetNotFound' });

      const metrics = collector.finalize(false);
      expect(metrics.stepResults.failed).toBe(1);
    });

    it('counts recovered steps with recovery method', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordStep({ stepId: 's1', ok: true }, 'observe_refresh');
      collector.recordStep({ stepId: 's2', ok: true }, 'healing_memory');
      collector.recordStep({ stepId: 's3', ok: true });

      const metrics = collector.finalize(true);
      expect(metrics.stepResults.total).toBe(3);
      expect(metrics.stepResults.passed).toBe(1);
      expect(metrics.stepResults.recovered).toBe(2);
      expect(metrics.fallbackLadderUsage).toEqual({
        observe_refresh: 1,
        healing_memory: 1,
      });
    });
  });

  describe('recordLlmCall', () => {
    it('accumulates LLM calls and tokens', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordLlmCall({ prompt: 100, completion: 50 });
      collector.recordLlmCall({ prompt: 200, completion: 80 });

      const metrics = collector.finalize(true);
      expect(metrics.llmCalls).toBe(2);
      expect(metrics.tokenUsage.prompt).toBe(300);
      expect(metrics.tokenUsage.completion).toBe(130);
    });
  });

  describe('recordPatch', () => {
    it('tracks patch count and success rate', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordPatch(true);
      collector.recordPatch(true);
      collector.recordPatch(false);

      const metrics = collector.finalize(true);
      expect(metrics.patchCount).toBe(3);
      expect(metrics.patchSuccessRate).toBeCloseTo(2 / 3);
    });

    it('reports 0 success rate with no patches', () => {
      collector.startRun('run-1', 'flow', 'v001');
      const metrics = collector.finalize(true);
      expect(metrics.patchCount).toBe(0);
      expect(metrics.patchSuccessRate).toBe(0);
    });
  });

  describe('recordHealingMemory', () => {
    it('tracks hits and misses', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordHealingMemory(true);
      collector.recordHealingMemory(true);
      collector.recordHealingMemory(false);

      const metrics = collector.finalize(true);
      expect(metrics.healingMemoryHits).toBe(2);
      expect(metrics.healingMemoryMisses).toBe(1);
    });
  });

  describe('recordCheckpointWait', () => {
    it('accumulates checkpoint wait time', () => {
      collector.startRun('run-1', 'flow', 'v001');

      collector.recordCheckpointWait(1000);
      collector.recordCheckpointWait(2500);

      const metrics = collector.finalize(true);
      expect(metrics.checkpointWaitMs).toBe(3500);
    });
  });

  describe('full lifecycle', () => {
    it('produces complete metrics for a realistic run', () => {
      collector.startRun('run-full', 'booking_flow', 'v003');

      // Step 1: passed normally
      collector.recordStep({ stepId: 'open', ok: true });

      // Step 2: failed, recovered via observe refresh
      collector.recordStep({ stepId: 'login', ok: true }, 'observe_refresh');
      collector.recordLlmCall({ prompt: 150, completion: 30 });

      // Step 3: passed normally
      collector.recordStep({ stepId: 'extract', ok: true });

      // Healing memory check
      collector.recordHealingMemory(true);
      collector.recordHealingMemory(false);

      // Patch applied
      collector.recordPatch(true);

      // Checkpoint wait
      collector.recordCheckpointWait(5000);

      // Step 4: passed
      collector.recordStep({ stepId: 'apply', ok: true });

      const metrics = collector.finalize(true);

      expect(metrics.runId).toBe('run-full');
      expect(metrics.flow).toBe('booking_flow');
      expect(metrics.version).toBe('v003');
      expect(metrics.success).toBe(true);
      expect(metrics.llmCalls).toBe(1);
      expect(metrics.tokenUsage).toEqual({ prompt: 150, completion: 30 });
      expect(metrics.patchCount).toBe(1);
      expect(metrics.patchSuccessRate).toBe(1);
      expect(metrics.healingMemoryHits).toBe(1);
      expect(metrics.healingMemoryMisses).toBe(1);
      expect(metrics.checkpointWaitMs).toBe(5000);
      expect(metrics.stepResults).toEqual({
        total: 4,
        passed: 3,
        failed: 0,
        recovered: 1,
      });
      expect(metrics.fallbackLadderUsage).toEqual({ observe_refresh: 1 });
    });
  });
});
