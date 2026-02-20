import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PatchWorkflow, type PatchSeverity } from '../../src/runner/patch-workflow.js';
import type { CheckpointHandler } from '../../src/runner/checkpoint.js';
import type { Recipe, PatchPayload } from '../../src/types/index.js';

// Mock fs module for versioning
vi.mock('node:fs/promises', () => ({
  mkdir: vi.fn().mockResolvedValue(undefined),
  writeFile: vi.fn().mockResolvedValue(undefined),
}));

function mockCheckpoint(decision: 'GO' | 'NOT_GO' = 'GO'): CheckpointHandler {
  return {
    requestApproval: vi.fn().mockResolvedValue(decision),
  };
}

function makeRecipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    domain: 'example.com',
    flow: 'test',
    version: 'v001',
    workflow: { id: 'test_flow', steps: [] },
    actions: {
      'login.submit': {
        instruction: 'find login button',
        preferred: {
          selector: '#login-btn',
          description: 'Login button',
          method: 'click',
        },
        observedAt: '2026-02-20T00:00:00Z',
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
    ...overrides,
  };
}

describe('PatchWorkflow', () => {
  let checkpoint: CheckpointHandler;
  let workflow: PatchWorkflow;

  beforeEach(() => {
    checkpoint = mockCheckpoint();
    workflow = new PatchWorkflow(checkpoint);
  });

  describe('classifyPatch', () => {
    it('classifies single actions.replace as minor', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'actions.replace', key: 'login.submit', value: {} }],
        reason: 'Updated selector',
      };
      expect(workflow.classifyPatch(payload)).toBe('minor');
    });

    it('classifies single selectors.replace as minor', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'selectors.replace', key: 'login.submit', value: {} }],
        reason: 'Updated selector',
      };
      expect(workflow.classifyPatch(payload)).toBe('minor');
    });

    it('classifies single actions.add as minor', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'actions.add', key: 'new.action', value: {} }],
        reason: 'Added new action',
      };
      expect(workflow.classifyPatch(payload)).toBe('minor');
    });

    it('classifies single selectors.add as minor', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'selectors.add', key: 'new.selector', value: {} }],
        reason: 'Added selector',
      };
      expect(workflow.classifyPatch(payload)).toBe('minor');
    });

    it('classifies workflow.update_expect as major', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'workflow.update_expect', step: 'login', value: [] }],
        reason: 'Changed expectations',
      };
      expect(workflow.classifyPatch(payload)).toBe('major');
    });

    it('classifies policies.update as major', () => {
      const payload: PatchPayload = {
        patch: [{ op: 'policies.update', key: 'seat_policy', value: {} }],
        reason: 'Updated policy',
      };
      expect(workflow.classifyPatch(payload)).toBe('major');
    });

    it('classifies multiple operations as major', () => {
      const payload: PatchPayload = {
        patch: [
          { op: 'actions.replace', key: 'a', value: {} },
          { op: 'selectors.replace', key: 'b', value: {} },
        ],
        reason: 'Multiple changes',
      };
      expect(workflow.classifyPatch(payload)).toBe('major');
    });
  });

  describe('applyAndVersionUp', () => {
    it('auto-applies minor patch without approval', async () => {
      const recipe = makeRecipe();
      const payload: PatchPayload = {
        patch: [{
          op: 'actions.replace',
          key: 'login.submit',
          value: {
            instruction: 'find login button',
            preferred: {
              selector: '#new-btn',
              description: 'New login button',
              method: 'click',
            },
            observedAt: '2026-02-21T00:00:00Z',
          },
        }],
        reason: 'Updated selector',
      };

      const result = await workflow.applyAndVersionUp(recipe, payload, '/tmp/test');

      expect(result.version).toBe('v002');
      expect(checkpoint.requestApproval).not.toHaveBeenCalled();
    });

    it('requests approval for major patch', async () => {
      const recipe = makeRecipe();
      const payload: PatchPayload = {
        patch: [{ op: 'workflow.update_expect', step: 'login', value: [{ kind: 'url_contains', value: '/home' }] }],
        reason: 'Changed redirect URL',
      };

      const result = await workflow.applyAndVersionUp(recipe, payload, '/tmp/test');

      expect(result.version).toBe('v002');
      expect(checkpoint.requestApproval).toHaveBeenCalledWith(
        'Major patch: Changed redirect URL. Apply?',
      );
    });

    it('throws when major patch rejected', async () => {
      checkpoint = mockCheckpoint('NOT_GO');
      workflow = new PatchWorkflow(checkpoint);

      const recipe = makeRecipe();
      const payload: PatchPayload = {
        patch: [{ op: 'policies.update', key: 'policy_v1', value: {} }],
        reason: 'Policy change',
      };

      await expect(
        workflow.applyAndVersionUp(recipe, payload, '/tmp/test'),
      ).rejects.toThrow('Patch rejected by user');
    });

    it('applies patch ops to recipe correctly', async () => {
      const recipe = makeRecipe();
      const newAction = {
        instruction: 'find new login',
        preferred: {
          selector: '#new-login',
          description: 'New login',
          method: 'click' as const,
        },
        observedAt: '2026-02-21T00:00:00Z',
      };
      const payload: PatchPayload = {
        patch: [{ op: 'actions.replace', key: 'login.submit', value: newAction }],
        reason: 'Updated login action',
      };

      const result = await workflow.applyAndVersionUp(recipe, payload, '/tmp/test');

      expect(result.actions['login.submit']).toEqual(newAction);
    });

    it('versions up from v001 to v002', async () => {
      const recipe = makeRecipe({ version: 'v001' });
      const payload: PatchPayload = {
        patch: [{ op: 'actions.replace', key: 'login.submit', value: makeRecipe().actions['login.submit'] }],
        reason: 'test',
      };

      const result = await workflow.applyAndVersionUp(recipe, payload, '/tmp/test');
      expect(result.version).toBe('v002');
    });

    it('versions up from v009 to v010', async () => {
      const recipe = makeRecipe({ version: 'v009' });
      const payload: PatchPayload = {
        patch: [{ op: 'actions.replace', key: 'login.submit', value: makeRecipe().actions['login.submit'] }],
        reason: 'test',
      };

      const result = await workflow.applyAndVersionUp(recipe, payload, '/tmp/test');
      expect(result.version).toBe('v010');
    });
  });
});
