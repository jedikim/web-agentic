import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { HealingMemory } from '../../src/memory/healing-memory.js';
import type { HealingEvidence } from '../../src/memory/healing-memory.js';
import { rm, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';
import type { ActionRef } from '../../src/types/action.js';

describe('HealingMemory', () => {
  let dir: string;
  let filePath: string;
  let memory: HealingMemory;

  const action1: ActionRef = {
    selector: '#login-btn',
    description: 'Login button',
    method: 'click',
  };

  const action2: ActionRef = {
    selector: '.submit-form',
    description: 'Submit form button',
    method: 'click',
  };

  const makeEvidence = (overrides?: Partial<HealingEvidence>): HealingEvidence => ({
    originalSelector: '#old-btn',
    healedSelector: '#login-btn',
    domContext: '<div><button id="login-btn">Login</button></div>',
    pageTitle: 'Login Page',
    pageUrl: 'https://example.com/login',
    method: 'observe',
    timestamp: new Date().toISOString(),
    ...overrides,
  });

  beforeEach(async () => {
    dir = join(tmpdir(), `healing-memory-test-${randomUUID()}`);
    await mkdir(dir, { recursive: true });
    filePath = join(dir, 'healing-memory.json');
    memory = new HealingMemory(filePath);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  describe('findMatch', () => {
    it('returns null when no entries exist', async () => {
      const result = await memory.findMatch('login.submit', 'https://example.com');
      expect(result).toBeNull();
    });

    it('returns a matching action for the targetKey', async () => {
      await memory.record('login.submit', action1, 'https://example.com/login', makeEvidence());
      const result = await memory.findMatch('login.submit', 'https://example.com/login');
      expect(result).toEqual(action1);
    });

    it('returns null for non-matching targetKey', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      const result = await memory.findMatch('checkout.submit', 'https://example.com');
      expect(result).toBeNull();
    });

    it('prefers same-domain matches', async () => {
      await memory.record(
        'login.submit',
        action1,
        'https://example.com/login',
        makeEvidence({ healedSelector: action1.selector }),
      );
      await memory.record(
        'login.submit',
        action2,
        'https://other.com/login',
        makeEvidence({ healedSelector: action2.selector }),
      );

      const result = await memory.findMatch('login.submit', 'https://example.com/dashboard');
      expect(result).toEqual(action1);
    });

    it('falls back to cross-domain matches when no same-domain exists', async () => {
      await memory.record(
        'login.submit',
        action2,
        'https://other.com/login',
        makeEvidence({ healedSelector: action2.selector }),
      );
      const result = await memory.findMatch('login.submit', 'https://example.com');
      expect(result).toEqual(action2);
    });

    it('prefers higher success count entries', async () => {
      await memory.record(
        'login.submit',
        action1,
        'https://example.com/v1',
        makeEvidence({ healedSelector: action1.selector }),
      );
      await memory.record(
        'login.submit',
        action1,
        'https://example.com/v1',
        makeEvidence({ healedSelector: action1.selector }),
      );
      await memory.record(
        'login.submit',
        action1,
        'https://example.com/v1',
        makeEvidence({ healedSelector: action1.selector }),
      );
      await memory.record(
        'login.submit',
        action2,
        'https://example.com/v2',
        makeEvidence({ healedSelector: action2.selector }),
      );

      const result = await memory.findMatch('login.submit', 'https://example.com/any');
      expect(result).toEqual(action1);
    });

    it('filters out entries below minConfidence threshold', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      // Record multiple failures to drop confidence below 0.6
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');

      // confidence = 1 / (1 + 3) = 0.25, below default 0.6
      const result = await memory.findMatch('login.submit', 'https://example.com');
      expect(result).toBeNull();
    });

    it('returns entries with custom minConfidence', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');

      // confidence = 0.25, use lower threshold
      const result = await memory.findMatch('login.submit', 'https://example.com', 0.2);
      expect(result).toEqual(action1);
    });

    it('prefers higher confidence entries over higher success count', async () => {
      // action1: 5 success, 5 fail -> confidence 0.5 (but we check >=0.6 so use minConfidence=0.4)
      await memory.record('login.submit', action1, 'https://example.com/a', makeEvidence());
      for (let i = 0; i < 4; i++) {
        await memory.record('login.submit', action1, 'https://example.com/a', makeEvidence());
      }
      for (let i = 0; i < 5; i++) {
        await memory.recordFailure('login.submit', 'https://example.com/a');
      }

      // action2: 2 success, 0 fail -> confidence 1.0
      await memory.record(
        'login.submit',
        action2,
        'https://example.com/b',
        makeEvidence({ healedSelector: action2.selector }),
      );
      await memory.record(
        'login.submit',
        action2,
        'https://example.com/b',
        makeEvidence({ healedSelector: action2.selector }),
      );

      const result = await memory.findMatch('login.submit', 'https://example.com/any', 0.4);
      expect(result).toEqual(action2);
    });
  });

  describe('record', () => {
    it('stores a new entry with evidence', async () => {
      const evidence = makeEvidence();
      await memory.record('login.submit', action1, 'https://example.com', evidence);
      const entries = await memory.getAll();
      expect(entries).toHaveLength(1);
      expect(entries[0].targetKey).toBe('login.submit');
      expect(entries[0].action).toEqual(action1);
      expect(entries[0].successCount).toBe(1);
      expect(entries[0].failCount).toBe(0);
      expect(entries[0].confidence).toBe(1.0);
      expect(entries[0].evidence).toEqual(evidence);
      expect(entries[0].domain).toBe('example.com');
    });

    it('increments successCount for duplicate entries', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      const entries = await memory.getAll();
      expect(entries).toHaveLength(1);
      expect(entries[0].successCount).toBe(2);
      expect(entries[0].confidence).toBe(1.0);
    });

    it('creates separate entries for different selectors', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.record(
        'login.submit',
        action2,
        'https://example.com',
        makeEvidence({ healedSelector: action2.selector }),
      );
      const entries = await memory.getAll();
      expect(entries).toHaveLength(2);
    });

    it('persists to disk and reloads correctly', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());

      // Create a new memory instance to read from disk
      const memory2 = new HealingMemory(filePath);
      const result = await memory2.findMatch('login.submit', 'https://example.com');
      expect(result).toEqual(action1);
    });

    it('recalculates confidence after recording success on a previously failed entry', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.recordFailure('login.submit', 'https://example.com');
      // confidence = 1/2 = 0.5
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      // confidence = 2/3 = 0.666...
      const entries = await memory.getAll();
      expect(entries[0].successCount).toBe(2);
      expect(entries[0].failCount).toBe(1);
      expect(entries[0].confidence).toBeCloseTo(2 / 3);
    });
  });

  describe('recordFailure', () => {
    it('increments failCount and recalculates confidence', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.recordFailure('login.submit', 'https://example.com');

      const entries = await memory.getAll();
      expect(entries[0].failCount).toBe(1);
      expect(entries[0].confidence).toBe(0.5); // 1 / (1 + 1)
    });

    it('sets lastFailAt timestamp', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.recordFailure('login.submit', 'https://example.com');

      const entries = await memory.getAll();
      expect(entries[0].lastFailAt).toBeDefined();
    });

    it('does nothing when no matching entries exist', async () => {
      await memory.recordFailure('nonexistent', 'https://example.com');
      const entries = await memory.getAll();
      expect(entries).toHaveLength(0);
    });

    it('updates all matching entries for same targetKey + url', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      await memory.record(
        'login.submit',
        action2,
        'https://example.com',
        makeEvidence({ healedSelector: action2.selector }),
      );
      await memory.recordFailure('login.submit', 'https://example.com');

      const entries = await memory.getAll();
      expect(entries[0].failCount).toBe(1);
      expect(entries[1].failCount).toBe(1);
    });
  });

  describe('prune', () => {
    it('removes entries below minConfidence', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      // Fail it multiple times to lower confidence
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');
      await memory.recordFailure('login.submit', 'https://example.com');
      // confidence = 1/5 = 0.2

      const pruned = await memory.prune({ minConfidence: 0.3 });
      expect(pruned).toBe(1);

      const entries = await memory.getAll();
      expect(entries).toHaveLength(0);
    });

    it('keeps entries above minConfidence', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      // confidence = 1.0

      const pruned = await memory.prune({ minConfidence: 0.3 });
      expect(pruned).toBe(0);

      const entries = await memory.getAll();
      expect(entries).toHaveLength(1);
    });

    it('removes entries older than maxAgeDays', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());

      // Manually set lastSuccessAt to 100 days ago
      const entries = await memory.getAll();
      const oldDate = new Date(Date.now() - 100 * 24 * 60 * 60 * 1000).toISOString();
      entries[0].lastSuccessAt = oldDate;
      // Save by re-writing
      const store = { entries };
      await writeFile(filePath, JSON.stringify(store, null, 2), 'utf-8');

      // Reload
      const memory2 = new HealingMemory(filePath);
      const pruned = await memory2.prune({ maxAgeDays: 30 });
      expect(pruned).toBe(1);
    });

    it('returns 0 when nothing to prune', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());
      const pruned = await memory.prune({ minConfidence: 0.3, maxAgeDays: 365 });
      expect(pruned).toBe(0);
    });
  });

  describe('getStats', () => {
    it('returns zero stats for empty memory', async () => {
      const stats = await memory.getStats();
      expect(stats.totalRecords).toBe(0);
      expect(stats.avgConfidence).toBe(0);
      expect(stats.hitRate).toBe(0);
      expect(stats.domainDistribution).toEqual({});
    });

    it('returns correct stats after recording', async () => {
      await memory.record(
        'login.submit',
        action1,
        'https://example.com/login',
        makeEvidence(),
      );
      await memory.record(
        'checkout.submit',
        action2,
        'https://shop.com/checkout',
        makeEvidence({ healedSelector: action2.selector }),
      );

      const stats = await memory.getStats();
      expect(stats.totalRecords).toBe(2);
      expect(stats.avgConfidence).toBe(1.0);
      expect(stats.domainDistribution).toEqual({
        'example.com': 1,
        'shop.com': 1,
      });
    });

    it('tracks hit rate across lookups', async () => {
      await memory.record('login.submit', action1, 'https://example.com', makeEvidence());

      // Hit
      await memory.findMatch('login.submit', 'https://example.com');
      // Miss
      await memory.findMatch('nonexistent', 'https://example.com');

      const stats = await memory.getStats();
      expect(stats.hitRate).toBe(0.5); // 1 hit / 2 lookups
    });
  });

  describe('legacy migration', () => {
    it('migrates legacy entries on load', async () => {
      const legacyStore = {
        entries: [
          {
            targetKey: 'login.submit',
            url: 'https://example.com',
            action: action1,
            healedAt: '2026-01-01T00:00:00.000Z',
            successCount: 3,
          },
        ],
      };
      await writeFile(filePath, JSON.stringify(legacyStore, null, 2), 'utf-8');

      const mem = new HealingMemory(filePath);
      const entries = await mem.getAll();

      expect(entries).toHaveLength(1);
      expect(entries[0].confidence).toBe(1.0);
      expect(entries[0].failCount).toBe(0);
      expect(entries[0].domain).toBe('example.com');
      expect(entries[0].evidence).toBeDefined();
      expect(entries[0].evidence.method).toBe('migration');
    });

    it('preserves successCount from legacy entries', async () => {
      const legacyStore = {
        entries: [
          {
            targetKey: 'login.submit',
            url: 'https://example.com',
            action: action1,
            healedAt: '2026-01-01T00:00:00.000Z',
            successCount: 5,
          },
        ],
      };
      await writeFile(filePath, JSON.stringify(legacyStore, null, 2), 'utf-8');

      const mem = new HealingMemory(filePath);
      const entries = await mem.getAll();
      expect(entries[0].successCount).toBe(5);
    });
  });
});
