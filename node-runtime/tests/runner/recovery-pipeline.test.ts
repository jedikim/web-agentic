import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  RecoveryPipeline,
  type AuthoringClientForRecovery,
  type FailureContext,
  type RecoveryPlan,
} from '../../src/runner/recovery-pipeline.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';
import type { HealingMemory } from '../../src/memory/healing-memory.js';
import type { BudgetGuard } from '../../src/runner/budget-guard.js';
import type { CheckpointHandler } from '../../src/runner/checkpoint.js';
import type { ObserveRefresher } from '../../src/engines/observe-refresher.js';
import type { PlaywrightFallbackEngine } from '../../src/engines/playwright-fallback.js';
import type { Recipe } from '../../src/types/index.js';

function mockObserveRefresher(action = null as any): ObserveRefresher {
  return {
    refresh: vi.fn().mockResolvedValue(action),
  } as unknown as ObserveRefresher;
}

function mockHealingMemory(action = null as any): HealingMemory {
  return {
    findMatch: vi.fn().mockResolvedValue(action),
    record: vi.fn().mockResolvedValue(undefined),
    getAll: vi.fn().mockResolvedValue([]),
  } as unknown as HealingMemory;
}

function mockBudgetGuard(overrides: Partial<BudgetGuard> = {}): BudgetGuard {
  return {
    canCallLlm: vi.fn().mockReturnValue(true),
    canCallAuthoring: vi.fn().mockReturnValue(true),
    canTakeScreenshot: vi.fn().mockReturnValue(true),
    recordLlmCall: vi.fn(),
    recordAuthoringCall: vi.fn(),
    recordScreenshot: vi.fn(),
    isOverBudget: vi.fn().mockReturnValue(false),
    getDowngradeAction: vi.fn().mockReturnValue(null),
    getMaxDomSnippetChars: vi.fn().mockReturnValue(2500),
    getAuthoringTimeoutMs: vi.fn().mockReturnValue(12000),
    ...overrides,
  } as unknown as BudgetGuard;
}

function mockCheckpoint(decision: 'GO' | 'NOT_GO' = 'GO'): CheckpointHandler {
  return {
    requestApproval: vi.fn().mockResolvedValue(decision),
  };
}

function mockEngine(overrides: Partial<BrowserEngine> = {}): BrowserEngine {
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    act: vi.fn().mockResolvedValue(true),
    observe: vi.fn().mockResolvedValue([]),
    extract: vi.fn().mockResolvedValue({}),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    currentUrl: vi.fn().mockResolvedValue('https://example.com'),
    currentTitle: vi.fn().mockResolvedValue('Example'),
    ...overrides,
  };
}

function mockPlaywright(overrides = {}): PlaywrightFallbackEngine {
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    act: vi.fn().mockResolvedValue(true),
    actWithFallback: vi.fn().mockResolvedValue(true),
    observe: vi.fn().mockResolvedValue([]),
    extract: vi.fn().mockResolvedValue({}),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    currentUrl: vi.fn().mockResolvedValue('https://example.com'),
    currentTitle: vi.fn().mockResolvedValue('Example'),
    ...overrides,
  } as unknown as PlaywrightFallbackEngine;
}

function mockAuthoringClient(
  response = { patch: [{ op: 'actions.replace' as const, key: 'login.submit', value: {} }], reason: 'Fixed selector' },
): AuthoringClientForRecovery {
  return {
    planPatch: vi.fn().mockResolvedValue(response),
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
        strategy: 'testid' as const,
      },
    },
    policies: {},
    fingerprints: {},
    ...overrides,
  };
}

function makeFailureContext(overrides: Partial<FailureContext> = {}): FailureContext {
  return {
    stepId: 'login',
    errorType: 'TargetNotFound',
    url: 'https://example.com/login',
    title: 'Login Page',
    failedSelector: 'login.submit',
    failedAction: {
      selector: '#login-btn',
      description: 'Login button',
      method: 'click',
    },
    ...overrides,
  };
}

describe('RecoveryPipeline', () => {
  let observeRefresher: ObserveRefresher;
  let healingMemory: HealingMemory;
  let budgetGuard: BudgetGuard;
  let checkpointHandler: CheckpointHandler;
  let stagehand: BrowserEngine;
  let playwright: PlaywrightFallbackEngine;
  let pipeline: RecoveryPipeline;

  beforeEach(() => {
    observeRefresher = mockObserveRefresher();
    healingMemory = mockHealingMemory();
    budgetGuard = mockBudgetGuard();
    checkpointHandler = mockCheckpoint();
    stagehand = mockEngine();
    playwright = mockPlaywright();
    pipeline = new RecoveryPipeline(
      observeRefresher,
      healingMemory,
      null,
      budgetGuard,
      checkpointHandler,
      stagehand,
      playwright,
    );
  });

  describe('retry', () => {
    it('recovers by retrying the failed action', async () => {
      const plan: RecoveryPlan = {
        actions: ['retry'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('retry');
      expect(stagehand.act).toHaveBeenCalled();
    });

    it('fails retry when no failed action', async () => {
      const plan: RecoveryPlan = {
        actions: ['retry'],
        context: makeFailureContext({ failedAction: undefined }),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
    });
  });

  describe('observe_refresh', () => {
    it('recovers via observe refresh when new action found', async () => {
      const newAction = {
        selector: '#new-btn',
        description: 'New login button',
        method: 'click' as const,
      };
      observeRefresher = mockObserveRefresher(newAction);
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['observe_refresh'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('observe_refresh');
      expect(result.action).toEqual(newAction);
    });

    it('skips observe_refresh when LLM budget exhausted', async () => {
      budgetGuard = mockBudgetGuard({
        canCallLlm: vi.fn().mockReturnValue(false),
      } as any);
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['observe_refresh'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
      expect(observeRefresher.refresh).not.toHaveBeenCalled();
    });

    it('records success in healing memory', async () => {
      const newAction = {
        selector: '#new-btn',
        description: 'New login button',
        method: 'click' as const,
      };
      observeRefresher = mockObserveRefresher(newAction);
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['observe_refresh'],
        context: makeFailureContext(),
      };

      await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(healingMemory.record).toHaveBeenCalledWith(
        'login.submit',
        newAction,
        'https://example.com/login',
      );
    });
  });

  describe('selector_fallback', () => {
    it('recovers via playwright selector fallback', async () => {
      const plan: RecoveryPlan = {
        actions: ['selector_fallback'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('selector_fallback');
    });

    it('fails when no playwright engine', async () => {
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        null,
      );

      const plan: RecoveryPlan = {
        actions: ['selector_fallback'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
    });

    it('fails when no selector entry exists', async () => {
      const plan: RecoveryPlan = {
        actions: ['selector_fallback'],
        context: makeFailureContext({ failedSelector: 'nonexistent' }),
      };

      const result = await pipeline.recover(plan, makeRecipe({ selectors: {} }), 'run-1');
      expect(result.recovered).toBe(false);
    });
  });

  describe('healing_memory', () => {
    it('recovers from healing memory match', async () => {
      const healedAction = {
        selector: '#healed-btn',
        description: 'Healed action',
        method: 'click' as const,
      };
      healingMemory = mockHealingMemory(healedAction);
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['healing_memory'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('healing_memory');
      expect(result.action).toEqual(healedAction);
    });

    it('fails when no healing memory match', async () => {
      const plan: RecoveryPlan = {
        actions: ['healing_memory'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
    });
  });

  describe('authoring_patch', () => {
    it('recovers via authoring service patch', async () => {
      const authoringClient = mockAuthoringClient();
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        authoringClient,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['authoring_patch'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('authoring_patch');
      expect(result.patchApplied).toBeDefined();
      expect(authoringClient.planPatch).toHaveBeenCalled();
    });

    it('fails when no authoring client configured', async () => {
      const plan: RecoveryPlan = {
        actions: ['authoring_patch'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
    });

    it('fails when authoring budget exhausted', async () => {
      budgetGuard = mockBudgetGuard({
        canCallAuthoring: vi.fn().mockReturnValue(false),
      } as any);
      const authoringClient = mockAuthoringClient();
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        authoringClient,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['authoring_patch'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
      expect(authoringClient.planPatch).not.toHaveBeenCalled();
    });
  });

  describe('checkpoint', () => {
    it('recovers when checkpoint approved (GO)', async () => {
      const plan: RecoveryPlan = {
        actions: ['checkpoint'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('checkpoint');
    });

    it('fails when checkpoint rejected (NOT_GO)', async () => {
      checkpointHandler = mockCheckpoint('NOT_GO');
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['checkpoint'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
      expect(result.method).toBe('checkpoint');
    });
  });

  describe('abort', () => {
    it('always returns not recovered', async () => {
      const plan: RecoveryPlan = {
        actions: ['abort'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
      expect(result.method).toBe('abort');
    });
  });

  describe('full ladder', () => {
    it('tries actions in order, succeeds on third attempt', async () => {
      // retry fails (act returns false), observe_refresh fails (null), selector_fallback succeeds
      stagehand = mockEngine({
        act: vi.fn().mockResolvedValue(false),
        currentUrl: vi.fn().mockResolvedValue('https://example.com'),
        currentTitle: vi.fn().mockResolvedValue('Example'),
        screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
      } as any);

      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['retry', 'observe_refresh', 'selector_fallback'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('selector_fallback');
    });

    it('returns not recovered when all actions fail', async () => {
      stagehand = mockEngine({
        act: vi.fn().mockResolvedValue(false),
        screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
        currentUrl: vi.fn().mockResolvedValue('https://example.com'),
        currentTitle: vi.fn().mockResolvedValue('Example'),
      } as any);
      playwright = mockPlaywright({
        actWithFallback: vi.fn().mockResolvedValue(false),
      });
      checkpointHandler = mockCheckpoint('NOT_GO');

      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['retry', 'observe_refresh', 'selector_fallback', 'healing_memory', 'checkpoint'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(false);
    });

    it('handles actions that throw without breaking the ladder', async () => {
      stagehand = mockEngine({
        act: vi.fn()
          .mockRejectedValueOnce(new Error('network error'))  // retry throws
          .mockResolvedValue(true),
        currentUrl: vi.fn().mockResolvedValue('https://example.com'),
        currentTitle: vi.fn().mockResolvedValue('Example'),
      } as any);

      const healedAction = {
        selector: '#healed-btn',
        description: 'Healed',
        method: 'click' as const,
      };
      healingMemory = mockHealingMemory(healedAction);

      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['retry', 'healing_memory'],
        context: makeFailureContext(),
      };

      const result = await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(result.recovered).toBe(true);
      expect(result.method).toBe('healing_memory');
    });
  });

  describe('budget checks', () => {
    it('records authoring call in budget guard', async () => {
      const authoringClient = mockAuthoringClient();
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        authoringClient,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['authoring_patch'],
        context: makeFailureContext(),
      };

      await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(budgetGuard.recordAuthoringCall).toHaveBeenCalled();
    });

    it('records LLM call in budget guard for observe refresh', async () => {
      const newAction = {
        selector: '#new-btn',
        description: 'Found',
        method: 'click' as const,
      };
      observeRefresher = mockObserveRefresher(newAction);
      pipeline = new RecoveryPipeline(
        observeRefresher,
        healingMemory,
        null,
        budgetGuard,
        checkpointHandler,
        stagehand,
        playwright,
      );

      const plan: RecoveryPlan = {
        actions: ['observe_refresh'],
        context: makeFailureContext(),
      };

      await pipeline.recover(plan, makeRecipe(), 'run-1');
      expect(budgetGuard.recordLlmCall).toHaveBeenCalled();
    });
  });
});
