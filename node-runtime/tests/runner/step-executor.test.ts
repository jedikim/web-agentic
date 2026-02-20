import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StepExecutor } from '../../src/runner/step-executor.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';
import type { HealingMemory } from '../../src/memory/healing-memory.js';
import type { BudgetGuard } from '../../src/runner/budget-guard.js';
import type { CheckpointHandler } from '../../src/runner/checkpoint.js';
import type { RunContext, WorkflowStep, Recipe } from '../../src/types/index.js';

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

function mockHealingMemory(): HealingMemory {
  return {
    findMatch: vi.fn().mockResolvedValue(null),
    record: vi.fn().mockResolvedValue(undefined),
    getAll: vi.fn().mockResolvedValue([]),
  } as unknown as HealingMemory;
}

function mockBudgetGuard(): BudgetGuard {
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
  } as unknown as BudgetGuard;
}

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
    workflow: {
      id: 'test_flow',
      steps: [],
    },
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

function makeContext(overrides: Partial<RunContext> = {}): RunContext {
  return {
    recipe: makeRecipe(),
    vars: {},
    budget: {
      maxLlmCallsPerRun: 2,
      maxPromptChars: 6000,
      maxDomSnippetChars: 2500,
      maxScreenshotPerFailure: 1,
      maxScreenshotPerCheckpoint: 2,
      maxAuthoringServiceCallsPerRun: 2,
      authoringServiceTimeoutMs: 12000,
    },
    usage: { llmCalls: 0, authoringCalls: 0, promptChars: 0, screenshots: 0 },
    runId: 'test-run-001',
    startedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe('StepExecutor', () => {
  let stagehand: BrowserEngine;
  let playwright: BrowserEngine;
  let healing: HealingMemory;
  let budget: BudgetGuard;
  let checkpoint: CheckpointHandler;
  let executor: StepExecutor;

  beforeEach(() => {
    stagehand = mockEngine();
    playwright = mockEngine();
    healing = mockHealingMemory();
    budget = mockBudgetGuard();
    checkpoint = mockCheckpoint();
    executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);
  });

  describe('goto', () => {
    it('navigates to URL', async () => {
      const step: WorkflowStep = { id: 'open', op: 'goto', args: { url: 'https://example.com' } };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(true);
      expect(result.stepId).toBe('open');
      expect(stagehand.goto).toHaveBeenCalledWith('https://example.com');
    });

    it('interpolates variables in URL', async () => {
      const step: WorkflowStep = { id: 'open', op: 'goto', args: { url: 'https://{{vars.domain}}/login' } };
      const context = makeContext({ vars: { domain: 'test.com' } });
      const result = await executor.execute(step, context);

      expect(result.ok).toBe(true);
      expect(stagehand.goto).toHaveBeenCalledWith('https://test.com/login');
    });

    it('fails when no URL provided', async () => {
      const step: WorkflowStep = { id: 'open', op: 'goto', args: {} };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(false);
    });
  });

  describe('act_cached', () => {
    it('succeeds with cached action (Level 1)', async () => {
      const step: WorkflowStep = { id: 'login', op: 'act_cached', targetKey: 'login.submit' };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(true);
      expect(stagehand.act).toHaveBeenCalled();
    });

    it('falls through to observe when cached action fails (Level 3)', async () => {
      stagehand = mockEngine({
        act: vi.fn()
          .mockRejectedValueOnce(new Error('Element not found'))
          .mockResolvedValue(true),
        observe: vi.fn().mockResolvedValue([
          { selector: '#new-btn', description: 'New login button', method: 'click' },
        ]),
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'login', op: 'act_cached', targetKey: 'login.submit' };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(true);
      expect(stagehand.observe).toHaveBeenCalled();
    });

    it('falls through to healing memory (Level 4)', async () => {
      stagehand = mockEngine({
        act: vi.fn()
          .mockRejectedValueOnce(new Error('not found'))   // Level 1 fail
          .mockResolvedValueOnce(true),                      // Healing memory action succeeds
        observe: vi.fn().mockResolvedValue([]),              // Level 3 empty
      });
      healing = mockHealingMemory();
      (healing.findMatch as ReturnType<typeof vi.fn>).mockResolvedValue({
        selector: '#healed-btn',
        description: 'Healed action',
        method: 'click',
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'login', op: 'act_cached', targetKey: 'login.submit' };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(true);
      expect(healing.findMatch).toHaveBeenCalled();
    });

    it('falls to screenshot checkpoint when all levels fail (Level 6)', async () => {
      stagehand = mockEngine({
        act: vi.fn().mockRejectedValue(new Error('not found')),
        observe: vi.fn().mockResolvedValue([]),
      });
      healing = mockHealingMemory();
      (budget.canCallLlm as ReturnType<typeof vi.fn>).mockReturnValue(false);
      checkpoint = mockCheckpoint('NOT_GO');
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'login', op: 'act_cached', targetKey: 'login.submit' };
      const result = await executor.execute(step, makeContext());

      expect(result.ok).toBe(false);
      expect(checkpoint.requestApproval).toHaveBeenCalled();
    });

    it('fails when no targetKey', async () => {
      const step: WorkflowStep = { id: 'login', op: 'act_cached' };
      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(false);
    });
  });

  describe('extract', () => {
    it('extracts data and stores in vars', async () => {
      stagehand = mockEngine({
        extract: vi.fn().mockResolvedValue([{ name: 'Seat A', price: 50 }]),
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const context = makeContext();
      const step: WorkflowStep = {
        id: 'get_seats',
        op: 'extract',
        args: { into: 'seats' },
      };

      const result = await executor.execute(step, context);
      expect(result.ok).toBe(true);
      expect(context.vars.seats).toEqual([{ name: 'Seat A', price: 50 }]);
    });

    it('fails on extraction error', async () => {
      stagehand = mockEngine({
        extract: vi.fn().mockRejectedValue(new Error('extraction empty')),
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'get_data', op: 'extract', args: { into: 'data' } };
      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(false);
      expect(result.errorType).toBe('ExtractionEmpty');
    });
  });

  describe('checkpoint', () => {
    it('succeeds when checkpoint approved', async () => {
      checkpoint = mockCheckpoint('GO');
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'check', op: 'checkpoint', args: { message: 'Continue?' } };
      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(true);
    });

    it('fails when checkpoint rejected', async () => {
      checkpoint = mockCheckpoint('NOT_GO');
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = { id: 'check', op: 'checkpoint', args: { message: 'Continue?' } };
      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(false);
    });
  });

  describe('wait', () => {
    it('waits specified milliseconds', async () => {
      const step: WorkflowStep = { id: 'pause', op: 'wait', args: { ms: 10 } };
      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(true);
    });
  });

  describe('expectations', () => {
    it('validates expectations after successful step', async () => {
      stagehand = mockEngine({
        currentUrl: vi.fn().mockResolvedValue('https://example.com/dashboard'),
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = {
        id: 'open',
        op: 'goto',
        args: { url: 'https://example.com/dashboard' },
        expect: [{ kind: 'url_contains', value: '/dashboard' }],
      };

      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(true);
    });

    it('fails when expectations are not met', async () => {
      stagehand = mockEngine({
        currentUrl: vi.fn().mockResolvedValue('https://example.com/error'),
      });
      executor = new StepExecutor(stagehand, playwright, healing, null, budget, checkpoint);

      const step: WorkflowStep = {
        id: 'open',
        op: 'goto',
        args: { url: 'https://example.com' },
        expect: [{ kind: 'url_contains', value: '/dashboard' }],
      };

      const result = await executor.execute(step, makeContext());
      expect(result.ok).toBe(false);
      expect(result.errorType).toBe('ExpectationFailed');
    });
  });

  describe('choose', () => {
    it('selects best candidate using policy', async () => {
      const context = makeContext({
        recipe: makeRecipe({
          policies: {
            seat_policy: {
              hard: [{ field: 'available', op: '==', value: true }],
              score: [{ when: { field: 'zone', op: '==', value: 'front' }, add: 30 }],
              tie_break: ['price_asc'],
              pick: 'argmax',
            },
          },
        }),
        vars: {
          seats: [
            { id: 'A', available: true, zone: 'back', price: 50 },
            { id: 'B', available: true, zone: 'front', price: 80 },
          ],
        },
      });

      const step: WorkflowStep = {
        id: 'pick',
        op: 'choose',
        args: { from: 'seats', policy: 'seat_policy', into: 'chosen' },
      };

      const result = await executor.execute(step, context);
      expect(result.ok).toBe(true);
      expect((context.vars.chosen as { id: string }).id).toBe('B');
    });

    it('fails when no candidates pass policy', async () => {
      const context = makeContext({
        recipe: makeRecipe({
          policies: {
            strict_policy: {
              hard: [{ field: 'available', op: '==', value: true }],
              score: [],
              tie_break: [],
              pick: 'first',
            },
          },
        }),
        vars: {
          items: [{ id: 'A', available: false }],
        },
      });

      const step: WorkflowStep = {
        id: 'pick',
        op: 'choose',
        args: { from: 'items', policy: 'strict_policy', into: 'chosen' },
      };

      const result = await executor.execute(step, context);
      expect(result.ok).toBe(false);
    });
  });
});
