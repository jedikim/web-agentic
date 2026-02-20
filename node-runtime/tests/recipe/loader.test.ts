import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { loadRecipe } from '../../src/recipe/loader.js';

const TEST_DIR = join(tmpdir(), 'web-agentic-test-loader');

const validWorkflow = {
  id: 'booking_flow',
  steps: [
    { id: 'open', op: 'goto', args: { url: 'https://example.com' } },
    { id: 'login', op: 'act_cached', targetKey: 'login.submit', expect: [{ kind: 'url_contains', value: '/dashboard' }] },
  ],
};

const validActions = {
  'login.submit': {
    instruction: 'find the login submit button',
    preferred: {
      selector: '/html/body/button[1]',
      description: 'Login button',
      method: 'click',
      arguments: [],
    },
    observedAt: '2026-02-20T23:00:00Z',
  },
};

const validSelectors = {
  'login.submit': {
    primary: '[data-testid="login-btn"]',
    fallbacks: ['button.login', '//button[@type="submit"]'],
    strategy: 'testid',
  },
};

const validPolicies = {
  seat_policy_v1: {
    hard: [{ field: 'available', op: '==', value: true }],
    score: [{ when: { field: 'zone', op: '==', value: 'front' }, add: 30 }],
    tie_break: ['price_asc'],
    pick: 'argmax',
  },
};

const validFingerprints = {
  login_page: {
    mustText: ['Sign In'],
    mustSelectors: ['input[name="email"]'],
    urlContains: '/login',
  },
};

async function writeRecipeFiles(basePath: string, version: string) {
  const dir = join(basePath, version);
  await mkdir(dir, { recursive: true });
  await Promise.all([
    writeFile(join(dir, 'workflow.json'), JSON.stringify(validWorkflow)),
    writeFile(join(dir, 'actions.json'), JSON.stringify(validActions)),
    writeFile(join(dir, 'selectors.json'), JSON.stringify(validSelectors)),
    writeFile(join(dir, 'policies.json'), JSON.stringify(validPolicies)),
    writeFile(join(dir, 'fingerprints.json'), JSON.stringify(validFingerprints)),
  ]);
}

describe('loadRecipe', () => {
  const recipePath = join(TEST_DIR, 'example.com', 'booking');

  beforeEach(async () => {
    await writeRecipeFiles(recipePath, 'v001');
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it('loads and validates a complete recipe', async () => {
    const recipe = await loadRecipe(recipePath, 'v001');

    expect(recipe.domain).toBe('example.com');
    expect(recipe.flow).toBe('booking');
    expect(recipe.version).toBe('v001');
    expect(recipe.workflow.id).toBe('booking_flow');
    expect(recipe.workflow.steps).toHaveLength(2);
    expect(recipe.actions['login.submit']).toBeDefined();
    expect(recipe.selectors['login.submit']).toBeDefined();
    expect(recipe.policies['seat_policy_v1']).toBeDefined();
    expect(recipe.fingerprints['login_page']).toBeDefined();
  });

  it('throws on missing file', async () => {
    await expect(loadRecipe(recipePath, 'v999')).rejects.toThrow();
  });

  it('throws on invalid workflow schema', async () => {
    const dir = join(recipePath, 'v002');
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, 'workflow.json'), JSON.stringify({ id: 'bad', steps: [] }));
    await writeFile(join(dir, 'actions.json'), JSON.stringify({}));
    await writeFile(join(dir, 'selectors.json'), JSON.stringify({}));
    await writeFile(join(dir, 'policies.json'), JSON.stringify({}));
    await writeFile(join(dir, 'fingerprints.json'), JSON.stringify({}));

    await expect(loadRecipe(recipePath, 'v002')).rejects.toThrow();
  });

  it('throws on invalid JSON', async () => {
    const dir = join(recipePath, 'v003');
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, 'workflow.json'), 'not json');
    await writeFile(join(dir, 'actions.json'), JSON.stringify({}));
    await writeFile(join(dir, 'selectors.json'), JSON.stringify({}));
    await writeFile(join(dir, 'policies.json'), JSON.stringify({}));
    await writeFile(join(dir, 'fingerprints.json'), JSON.stringify({}));

    await expect(loadRecipe(recipePath, 'v003')).rejects.toThrow();
  });
});
