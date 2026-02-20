import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { bundleTrace, TraceBundler } from '../../src/logging/trace-bundler.js';
import { writeFile, mkdir, rm, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

describe('bundleTrace', () => {
  let runDir: string;

  beforeEach(async () => {
    runDir = join(tmpdir(), `trace-bundler-test-${randomUUID()}`);
    await mkdir(runDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(runDir, { recursive: true, force: true });
  });

  it('collects screenshots', async () => {
    const png = Buffer.from('fake-png');
    await writeFile(join(runDir, 'step_login.png'), png);
    await writeFile(join(runDir, 'step_extract.png'), png);

    const bundle = await bundleTrace(runDir);

    expect(bundle.screenshots).toHaveLength(2);
    expect(bundle.screenshots.map((s) => s.filename).sort()).toEqual([
      'step_extract.png',
      'step_login.png',
    ]);
  });

  it('collects DOM snippets', async () => {
    await writeFile(join(runDir, 'dom_step1.html'), '<div>hello</div>');

    const bundle = await bundleTrace(runDir);

    expect(bundle.domSnippets).toHaveLength(1);
    expect(bundle.domSnippets[0].filename).toBe('dom_step1.html');
    expect(bundle.domSnippets[0].content.toString()).toBe('<div>hello</div>');
  });

  it('collects logs.jsonl', async () => {
    const logs = '{"stepId":"s1","ok":true}\n{"stepId":"s2","ok":false}\n';
    await writeFile(join(runDir, 'logs.jsonl'), logs);

    const bundle = await bundleTrace(runDir);

    expect(bundle.logs).toBe(logs);
  });

  it('collects summary.md', async () => {
    const summary = '# Run Summary\n- Result: Success\n';
    await writeFile(join(runDir, 'summary.md'), summary);

    const bundle = await bundleTrace(runDir);

    expect(bundle.summary).toBe(summary);
  });

  it('handles empty run directory', async () => {
    const bundle = await bundleTrace(runDir);

    expect(bundle.screenshots).toHaveLength(0);
    expect(bundle.domSnippets).toHaveLength(0);
    expect(bundle.logs).toBeNull();
    expect(bundle.summary).toBeNull();
  });

  it('returns the run directory path', async () => {
    const bundle = await bundleTrace(runDir);
    expect(bundle.runDir).toBe(runDir);
  });
});

describe('TraceBundler', () => {
  let runDir: string;
  let outputDir: string;
  let bundler: TraceBundler;

  beforeEach(async () => {
    runDir = join(tmpdir(), `trace-bundler-class-test-${randomUUID()}`);
    outputDir = join(tmpdir(), `trace-bundler-output-${randomUUID()}`);
    await mkdir(runDir, { recursive: true });
    bundler = new TraceBundler();
  });

  afterEach(async () => {
    await rm(runDir, { recursive: true, force: true });
    await rm(outputDir, { recursive: true, force: true });
  });

  describe('createBundle', () => {
    it('creates a bundle from a run directory with logs', async () => {
      const logs = [
        '{"stepId":"s1","ok":true,"op":"goto","timestamp":"2026-01-01T00:00:00Z","durationMs":100}',
        '{"stepId":"s2","ok":true,"op":"act_cached","targetKey":"login.submit","durationMs":200}',
        '{"stepId":"s3","ok":false,"op":"extract","errorType":"ExtractionEmpty","durationMs":50}',
      ].join('\n');
      await writeFile(join(runDir, 'logs.jsonl'), logs);

      const bundle = await bundler.createBundle(runDir);

      expect(bundle.steps).toHaveLength(3);
      expect(bundle.steps[0].stepId).toBe('s1');
      expect(bundle.steps[0].op).toBe('goto');
      expect(bundle.steps[0].result.ok).toBe(true);
      expect(bundle.steps[1].targetKey).toBe('login.submit');
      expect(bundle.steps[2].result.ok).toBe(false);
      expect(bundle.steps[2].result.errorType).toBe('ExtractionEmpty');
    });

    it('includes metadata counts', async () => {
      const logs = [
        '{"stepId":"s1","ok":true,"op":"goto","durationMs":100}',
        '{"stepId":"s2","ok":false,"op":"act_cached","durationMs":200,"recoveryMethod":"observe"}',
        '{"stepId":"s3","ok":true,"op":"extract","durationMs":50}',
      ].join('\n');
      await writeFile(join(runDir, 'logs.jsonl'), logs);

      const bundle = await bundler.createBundle(runDir);

      expect(bundle.metadata.totalSteps).toBe(3);
      expect(bundle.metadata.passedSteps).toBe(2);
      expect(bundle.metadata.failedSteps).toBe(1);
      expect(bundle.metadata.recoveredSteps).toBe(1);
    });

    it('detects screenshot and DOM snippet files for steps', async () => {
      const logs = '{"stepId":"login","ok":true,"op":"act_cached","durationMs":100}';
      await writeFile(join(runDir, 'logs.jsonl'), logs);
      await writeFile(join(runDir, 'step_login.png'), Buffer.from('fake-png'));
      await writeFile(join(runDir, 'dom_login.html'), '<div>login form</div>');

      const bundle = await bundler.createBundle(runDir);

      expect(bundle.steps[0].screenshotPath).toBe('step_login.png');
      expect(bundle.steps[0].domSnippetPath).toBe('dom_login.html');
    });

    it('reads trace-meta.json for flow/version/runId', async () => {
      const meta = { flow: 'booking', version: 'v003', runId: 'run-123', llmCalls: 2, patchesApplied: 1 };
      await writeFile(join(runDir, 'trace-meta.json'), JSON.stringify(meta));
      await writeFile(join(runDir, 'logs.jsonl'), '{"stepId":"s1","ok":true,"op":"goto","durationMs":10}');

      const bundle = await bundler.createBundle(runDir);

      expect(bundle.flow).toBe('booking');
      expect(bundle.version).toBe('v003');
      expect(bundle.runId).toBe('run-123');
      expect(bundle.metadata.llmCalls).toBe(2);
      expect(bundle.metadata.patchesApplied).toBe(1);
    });

    it('handles empty run directory', async () => {
      const bundle = await bundler.createBundle(runDir);
      expect(bundle.steps).toHaveLength(0);
      expect(bundle.metadata.totalSteps).toBe(0);
    });
  });

  describe('saveBundle and loadBundle', () => {
    it('saves and loads a bundle roundtrip', async () => {
      const logs = '{"stepId":"s1","ok":true,"op":"goto","durationMs":100}';
      await writeFile(join(runDir, 'logs.jsonl'), logs);

      const bundle = await bundler.createBundle(runDir);
      const savedPath = await bundler.saveBundle(bundle, outputDir);

      expect(savedPath).toBe(join(outputDir, 'trace.json'));

      const loaded = await bundler.loadBundle(savedPath);
      expect(loaded.steps).toHaveLength(1);
      expect(loaded.steps[0].stepId).toBe('s1');
      expect(loaded.metadata.totalSteps).toBe(1);
    });

    it('creates output directory if it does not exist', async () => {
      const nestedOutput = join(outputDir, 'nested', 'dir');
      const bundle = await bundler.createBundle(runDir);
      const savedPath = await bundler.saveBundle(bundle, nestedOutput);

      const content = await readFile(savedPath, 'utf-8');
      const parsed = JSON.parse(content);
      expect(parsed.steps).toBeDefined();
    });

    it('saves bundle as formatted JSON', async () => {
      const bundle = await bundler.createBundle(runDir);
      const savedPath = await bundler.saveBundle(bundle, outputDir);

      const content = await readFile(savedPath, 'utf-8');
      // Check it's indented (formatted)
      expect(content).toContain('\n');
      expect(content).toContain('  ');
    });
  });
});
