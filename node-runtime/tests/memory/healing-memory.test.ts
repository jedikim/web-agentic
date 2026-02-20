import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { HealingMemory } from '../../src/memory/healing-memory.js';
import { rm, mkdir } from 'node:fs/promises';
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
      await memory.record('login.submit', action1, 'https://example.com/login');
      const result = await memory.findMatch('login.submit', 'https://example.com/login');
      expect(result).toEqual(action1);
    });

    it('returns null for non-matching targetKey', async () => {
      await memory.record('login.submit', action1, 'https://example.com');
      const result = await memory.findMatch('checkout.submit', 'https://example.com');
      expect(result).toBeNull();
    });

    it('prefers same-domain matches', async () => {
      await memory.record('login.submit', action1, 'https://example.com/login');
      await memory.record('login.submit', action2, 'https://other.com/login');

      const result = await memory.findMatch('login.submit', 'https://example.com/dashboard');
      expect(result).toEqual(action1);
    });

    it('falls back to cross-domain matches when no same-domain exists', async () => {
      await memory.record('login.submit', action2, 'https://other.com/login');
      const result = await memory.findMatch('login.submit', 'https://example.com');
      expect(result).toEqual(action2);
    });

    it('prefers higher success count entries', async () => {
      await memory.record('login.submit', action1, 'https://example.com/v1');
      await memory.record('login.submit', action1, 'https://example.com/v1');
      await memory.record('login.submit', action1, 'https://example.com/v1');
      await memory.record('login.submit', action2, 'https://example.com/v2');

      const result = await memory.findMatch('login.submit', 'https://example.com/any');
      expect(result).toEqual(action1);
    });
  });

  describe('record', () => {
    it('stores a new entry', async () => {
      await memory.record('login.submit', action1, 'https://example.com');
      const entries = await memory.getAll();
      expect(entries).toHaveLength(1);
      expect(entries[0].targetKey).toBe('login.submit');
      expect(entries[0].action).toEqual(action1);
      expect(entries[0].successCount).toBe(1);
    });

    it('increments successCount for duplicate entries', async () => {
      await memory.record('login.submit', action1, 'https://example.com');
      await memory.record('login.submit', action1, 'https://example.com');
      const entries = await memory.getAll();
      expect(entries).toHaveLength(1);
      expect(entries[0].successCount).toBe(2);
    });

    it('creates separate entries for different selectors', async () => {
      await memory.record('login.submit', action1, 'https://example.com');
      await memory.record('login.submit', action2, 'https://example.com');
      const entries = await memory.getAll();
      expect(entries).toHaveLength(2);
    });

    it('persists to disk and reloads correctly', async () => {
      await memory.record('login.submit', action1, 'https://example.com');

      // Create a new memory instance to read from disk
      const memory2 = new HealingMemory(filePath);
      const result = await memory2.findMatch('login.submit', 'https://example.com');
      expect(result).toEqual(action1);
    });
  });
});
