import { describe, it, expect, afterEach } from 'vitest';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { readFile } from 'node:fs/promises';
import { nextVersion, saveRecipeVersion } from '../../src/recipe/versioning.js';
import type { Recipe } from '../../src/types/index.js';

const TEST_DIR = join(tmpdir(), 'web-agentic-test-versioning');

describe('nextVersion', () => {
  it('increments v001 to v002', () => {
    expect(nextVersion('v001')).toBe('v002');
  });

  it('increments v009 to v010', () => {
    expect(nextVersion('v009')).toBe('v010');
  });

  it('increments v099 to v100', () => {
    expect(nextVersion('v099')).toBe('v100');
  });

  it('increments v999 to v1000', () => {
    expect(nextVersion('v999')).toBe('v1000');
  });
});

describe('saveRecipeVersion', () => {
  const basePath = join(TEST_DIR, 'example.com', 'booking');

  const recipe: Recipe = {
    domain: 'example.com',
    flow: 'booking',
    version: 'v001',
    workflow: {
      id: 'booking_flow',
      steps: [{ id: 'open', op: 'goto', args: { url: 'https://example.com' } }],
    },
    actions: {},
    selectors: {},
    policies: {},
    fingerprints: {},
  };

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it('saves recipe files to new version directory', async () => {
    const newVersion = await saveRecipeVersion(basePath, recipe);
    expect(newVersion).toBe('v002');

    const workflowRaw = await readFile(join(basePath, 'v002', 'workflow.json'), 'utf-8');
    const workflow = JSON.parse(workflowRaw);
    expect(workflow.id).toBe('booking_flow');
    expect(workflow.steps).toHaveLength(1);
  });

  it('saves all 5 JSON files', async () => {
    await saveRecipeVersion(basePath, recipe);
    const dir = join(basePath, 'v002');

    const files = ['workflow.json', 'actions.json', 'selectors.json', 'policies.json', 'fingerprints.json'];
    for (const file of files) {
      const content = await readFile(join(dir, file), 'utf-8');
      expect(() => JSON.parse(content)).not.toThrow();
    }
  });
});
