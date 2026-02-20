import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { RunLogger } from '../../src/logging/run-logger.js';
import { readFile, rm, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

describe('RunLogger', () => {
  let runDir: string;
  let logger: RunLogger;

  beforeEach(() => {
    runDir = join(tmpdir(), `run-logger-test-${randomUUID()}`);
    logger = new RunLogger(runDir);
  });

  afterEach(async () => {
    await rm(runDir, { recursive: true, force: true });
  });

  describe('logStep', () => {
    it('creates the run directory and logs.jsonl', async () => {
      await logger.logStep({ stepId: 'step1', ok: true });
      const content = await readFile(join(runDir, 'logs.jsonl'), 'utf-8');
      const lines = content.trim().split('\n');
      expect(lines).toHaveLength(1);
      const entry = JSON.parse(lines[0]);
      expect(entry.stepId).toBe('step1');
      expect(entry.ok).toBe(true);
      expect(entry.timestamp).toBeDefined();
    });

    it('appends multiple step results', async () => {
      await logger.logStep({ stepId: 'step1', ok: true });
      await logger.logStep({ stepId: 'step2', ok: false, errorType: 'TargetNotFound', message: 'element missing' });
      const content = await readFile(join(runDir, 'logs.jsonl'), 'utf-8');
      const lines = content.trim().split('\n');
      expect(lines).toHaveLength(2);
      const entry2 = JSON.parse(lines[1]);
      expect(entry2.stepId).toBe('step2');
      expect(entry2.ok).toBe(false);
      expect(entry2.errorType).toBe('TargetNotFound');
    });
  });

  describe('saveScreenshot', () => {
    it('saves a screenshot file', async () => {
      const buffer = Buffer.from('fake-png-data');
      await logger.saveScreenshot('login', buffer);
      const saved = await readFile(join(runDir, 'step_login.png'));
      expect(saved.equals(buffer)).toBe(true);
    });
  });

  describe('saveDomSnippet', () => {
    it('saves a DOM snippet file', async () => {
      const html = '<div class="target">Hello</div>';
      await logger.saveDomSnippet('extract1', html);
      const saved = await readFile(join(runDir, 'dom_extract1.html'), 'utf-8');
      expect(saved).toBe(html);
    });
  });

  describe('getRunDir', () => {
    it('returns the run directory path', () => {
      expect(logger.getRunDir()).toBe(runDir);
    });
  });
});
