import { describe, it, expect } from 'vitest';
import { applyPatch } from '../../src/recipe/patch-merger.js';
import type { Recipe, PatchPayload } from '../../src/types/index.js';

function makeRecipe(): Recipe {
  return {
    domain: 'example.com',
    flow: 'booking',
    version: 'v001',
    workflow: {
      id: 'booking_flow',
      steps: [
        { id: 'open', op: 'goto', args: { url: 'https://example.com' } },
        { id: 'login', op: 'act_cached', targetKey: 'login.submit', expect: [{ kind: 'url_contains', value: '/dashboard' }] },
      ],
    },
    actions: {
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
    },
    selectors: {
      'login.submit': {
        primary: '[data-testid="login-btn"]',
        fallbacks: ['button.login'],
        strategy: 'testid',
      },
    },
    policies: {},
    fingerprints: {},
  };
}

describe('applyPatch', () => {
  it('replaces an action', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'actions.replace',
          key: 'login.submit',
          value: {
            instruction: 'find the sign in button',
            preferred: {
              selector: '/html/body/button[2]',
              description: 'Sign in button',
              method: 'click',
              arguments: [],
            },
            observedAt: '2026-02-21T00:00:00Z',
          },
        },
      ],
      reason: 'Login button moved',
    };

    const result = applyPatch(recipe, patch);
    expect(result.actions['login.submit'].preferred.selector).toBe('/html/body/button[2]');
    // Original recipe should be unchanged (immutability)
    expect(recipe.actions['login.submit'].preferred.selector).toBe('/html/body/button[1]');
  });

  it('adds a new action', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'actions.add',
          key: 'search.submit',
          value: {
            instruction: 'find the search button',
            preferred: {
              selector: '#search-btn',
              description: 'Search button',
              method: 'click',
            },
            observedAt: '2026-02-21T00:00:00Z',
          },
        },
      ],
      reason: 'New search action needed',
    };

    const result = applyPatch(recipe, patch);
    expect(result.actions['search.submit']).toBeDefined();
    expect(result.actions['login.submit']).toBeDefined();
  });

  it('throws when adding duplicate action key', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'actions.add',
          key: 'login.submit',
          value: { instruction: 'dup', preferred: { selector: 'x', description: 'x', method: 'click' }, observedAt: 'now' },
        },
      ],
      reason: 'Duplicate',
    };

    expect(() => applyPatch(recipe, patch)).toThrow('already exists');
  });

  it('adds a new selector', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'selectors.add',
          key: 'search.input',
          value: {
            primary: '[data-testid="search"]',
            fallbacks: ['input.search'],
            strategy: 'testid',
          },
        },
      ],
      reason: 'New selector',
    };

    const result = applyPatch(recipe, patch);
    expect(result.selectors['search.input']).toBeDefined();
  });

  it('replaces a selector', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'selectors.replace',
          key: 'login.submit',
          value: {
            primary: '[data-testid="sign-in"]',
            fallbacks: [],
            strategy: 'testid',
          },
        },
      ],
      reason: 'Selector changed',
    };

    const result = applyPatch(recipe, patch);
    expect(result.selectors['login.submit'].primary).toBe('[data-testid="sign-in"]');
  });

  it('updates workflow step expectations', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'workflow.update_expect',
          step: 'login',
          value: [{ kind: 'url_contains', value: '/home' }],
        },
      ],
      reason: 'Redirect changed',
    };

    const result = applyPatch(recipe, patch);
    const loginStep = result.workflow.steps.find((s) => s.id === 'login');
    expect(loginStep?.expect).toEqual([{ kind: 'url_contains', value: '/home' }]);
    // Original unchanged
    const origStep = recipe.workflow.steps.find((s) => s.id === 'login');
    expect(origStep?.expect).toEqual([{ kind: 'url_contains', value: '/dashboard' }]);
  });

  it('updates a policy', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'policies.update',
          key: 'seat_policy_v1',
          value: {
            hard: [{ field: 'available', op: '==', value: true }],
            score: [],
            tie_break: ['price_asc'],
            pick: 'argmax',
          },
        },
      ],
      reason: 'New policy',
    };

    const result = applyPatch(recipe, patch);
    expect(result.policies['seat_policy_v1']).toBeDefined();
  });

  it('applies multiple ops in sequence', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [
        {
          op: 'actions.replace',
          key: 'login.submit',
          value: {
            instruction: 'updated',
            preferred: { selector: '#new', description: 'New', method: 'click' },
            observedAt: 'now',
          },
        },
        {
          op: 'workflow.update_expect',
          step: 'login',
          value: [{ kind: 'title_contains', value: 'Dashboard' }],
        },
      ],
      reason: 'Multiple fixes',
    };

    const result = applyPatch(recipe, patch);
    expect(result.actions['login.submit'].preferred.selector).toBe('#new');
    expect(result.workflow.steps.find((s) => s.id === 'login')?.expect).toEqual([
      { kind: 'title_contains', value: 'Dashboard' },
    ]);
  });

  it('throws on missing key for actions.replace', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [{ op: 'actions.replace', value: {} }],
      reason: 'bad',
    };
    expect(() => applyPatch(recipe, patch)).toThrow('requires a key');
  });

  it('throws on missing step for workflow.update_expect', () => {
    const recipe = makeRecipe();
    const patch: PatchPayload = {
      patch: [{ op: 'workflow.update_expect', value: [] }],
      reason: 'bad',
    };
    expect(() => applyPatch(recipe, patch)).toThrow('requires a step');
  });
});
