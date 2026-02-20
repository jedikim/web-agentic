import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { bundleTrace } from '../../src/logging/trace-bundler.js';
import { writeFile, mkdir, rm } from 'node:fs/promises';
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
