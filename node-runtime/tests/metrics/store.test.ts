import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { MetricsStore } from '../../src/metrics/store.js';
import type { RunMetrics } from '../../src/metrics/collector.js';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

function makeMetrics(overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    runId: `run-${randomUUID().slice(0, 8)}`,
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

describe('MetricsStore', () => {
  let storeDir: string;
  let store: MetricsStore;

  beforeEach(() => {
    storeDir = join(tmpdir(), `metrics-store-test-${randomUUID()}`);
    store = new MetricsStore(storeDir);
  });

  afterEach(async () => {
    await rm(storeDir, { recursive: true, force: true });
  });

  describe('save and load', () => {
    it('saves and loads a single run', async () => {
      const metrics = makeMetrics({ runId: 'run-save-test' });
      await store.save(metrics);

      const loaded = await store.load('run-save-test');
      expect(loaded).not.toBeNull();
      expect(loaded!.runId).toBe('run-save-test');
      expect(loaded!.flow).toBe('booking_flow');
      expect(loaded!.success).toBe(true);
    });

    it('returns null for non-existent run', async () => {
      const loaded = await store.load('non-existent');
      expect(loaded).toBeNull();
    });

    it('overwrites existing metrics on save', async () => {
      const m1 = makeMetrics({ runId: 'run-overwrite', success: true });
      await store.save(m1);

      const m2 = makeMetrics({ runId: 'run-overwrite', success: false });
      await store.save(m2);

      const loaded = await store.load('run-overwrite');
      expect(loaded!.success).toBe(false);
    });
  });

  describe('loadAll', () => {
    it('loads all saved metrics', async () => {
      await store.save(makeMetrics({ runId: 'r1', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', startedAt: '2026-02-20T11:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r3', startedAt: '2026-02-20T12:00:00Z' }));

      const all = await store.loadAll();
      expect(all).toHaveLength(3);
    });

    it('returns results sorted by startedAt ascending', async () => {
      await store.save(makeMetrics({ runId: 'r3', startedAt: '2026-02-20T12:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r1', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', startedAt: '2026-02-20T11:00:00Z' }));

      const all = await store.loadAll();
      expect(all.map((m) => m.runId)).toEqual(['r1', 'r2', 'r3']);
    });

    it('returns empty array when no metrics exist', async () => {
      const all = await store.loadAll();
      expect(all).toEqual([]);
    });

    it('filters by flow', async () => {
      await store.save(makeMetrics({ runId: 'r1', flow: 'booking' }));
      await store.save(makeMetrics({ runId: 'r2', flow: 'login' }));
      await store.save(makeMetrics({ runId: 'r3', flow: 'booking' }));

      const filtered = await store.loadAll({ flow: 'booking' });
      expect(filtered).toHaveLength(2);
      expect(filtered.every((m) => m.flow === 'booking')).toBe(true);
    });

    it('filters by since date', async () => {
      await store.save(makeMetrics({ runId: 'r1', startedAt: '2026-02-19T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r3', startedAt: '2026-02-21T10:00:00Z' }));

      const filtered = await store.loadAll({ since: '2026-02-20T00:00:00Z' });
      expect(filtered).toHaveLength(2);
      expect(filtered.map((m) => m.runId)).toEqual(['r2', 'r3']);
    });

    it('filters by until date', async () => {
      await store.save(makeMetrics({ runId: 'r1', startedAt: '2026-02-19T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r3', startedAt: '2026-02-21T10:00:00Z' }));

      const filtered = await store.loadAll({ until: '2026-02-20T12:00:00Z' });
      expect(filtered).toHaveLength(2);
      expect(filtered.map((m) => m.runId)).toEqual(['r1', 'r2']);
    });

    it('combines flow and date filters', async () => {
      await store.save(makeMetrics({ runId: 'r1', flow: 'booking', startedAt: '2026-02-19T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', flow: 'booking', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r3', flow: 'login', startedAt: '2026-02-20T10:00:00Z' }));

      const filtered = await store.loadAll({ flow: 'booking', since: '2026-02-20T00:00:00Z' });
      expect(filtered).toHaveLength(1);
      expect(filtered[0].runId).toBe('r2');
    });
  });

  describe('loadRecent', () => {
    it('loads the last N runs by startedAt', async () => {
      await store.save(makeMetrics({ runId: 'r1', startedAt: '2026-02-20T10:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r2', startedAt: '2026-02-20T11:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r3', startedAt: '2026-02-20T12:00:00Z' }));
      await store.save(makeMetrics({ runId: 'r4', startedAt: '2026-02-20T13:00:00Z' }));

      const recent = await store.loadRecent(2);
      expect(recent).toHaveLength(2);
      expect(recent.map((m) => m.runId)).toEqual(['r3', 'r4']);
    });

    it('returns all if count exceeds total', async () => {
      await store.save(makeMetrics({ runId: 'r1' }));
      const recent = await store.loadRecent(10);
      expect(recent).toHaveLength(1);
    });

    it('returns empty for count 0', async () => {
      await store.save(makeMetrics({ runId: 'r1' }));
      const recent = await store.loadRecent(0);
      expect(recent).toHaveLength(0);
    });
  });
});
