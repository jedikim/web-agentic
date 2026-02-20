import { describe, it, expect, beforeEach } from 'vitest';
import { BudgetGuard } from '../../src/runner/budget-guard.js';
import type { BudgetConfig } from '../../src/types/budget.js';

const defaultConfig: BudgetConfig = {
  budget: {
    maxLlmCallsPerRun: 2,
    maxPromptChars: 6000,
    maxDomSnippetChars: 2500,
    maxScreenshotPerFailure: 1,
    maxScreenshotPerCheckpoint: 2,
    maxAuthoringServiceCallsPerRun: 2,
    authoringServiceTimeoutMs: 12000,
  },
  downgradeOrder: [
    'trim_dom',
    'drop_history',
    'observe_scope_narrow',
    'require_human_checkpoint',
  ],
};

describe('BudgetGuard', () => {
  let guard: BudgetGuard;

  beforeEach(() => {
    guard = new BudgetGuard(defaultConfig);
  });

  describe('canCallLlm', () => {
    it('returns true when under budget', () => {
      expect(guard.canCallLlm()).toBe(true);
    });

    it('returns false when at limit', () => {
      guard.recordLlmCall(1000);
      guard.recordLlmCall(1000);
      expect(guard.canCallLlm()).toBe(false);
    });

    it('returns true after one call (limit is 2)', () => {
      guard.recordLlmCall(1000);
      expect(guard.canCallLlm()).toBe(true);
    });
  });

  describe('canCallAuthoring', () => {
    it('returns true when under budget', () => {
      expect(guard.canCallAuthoring()).toBe(true);
    });

    it('returns false when at limit', () => {
      guard.recordAuthoringCall();
      guard.recordAuthoringCall();
      expect(guard.canCallAuthoring()).toBe(false);
    });
  });

  describe('canTakeScreenshot', () => {
    it('allows failure screenshots within budget', () => {
      expect(guard.canTakeScreenshot(false)).toBe(true);
    });

    it('blocks failure screenshots over limit', () => {
      guard.recordScreenshot();
      expect(guard.canTakeScreenshot(false)).toBe(false);
    });

    it('allows checkpoint screenshots with higher limit', () => {
      guard.recordScreenshot();
      expect(guard.canTakeScreenshot(true)).toBe(true);
    });

    it('blocks checkpoint screenshots at limit', () => {
      guard.recordScreenshot();
      guard.recordScreenshot();
      expect(guard.canTakeScreenshot(true)).toBe(false);
    });
  });

  describe('recordLlmCall', () => {
    it('tracks prompt chars', () => {
      guard.recordLlmCall(3000);
      expect(guard.currentUsage.promptChars).toBe(3000);
      expect(guard.currentUsage.llmCalls).toBe(1);
    });

    it('accumulates prompt chars', () => {
      guard.recordLlmCall(2000);
      guard.recordLlmCall(3000);
      expect(guard.currentUsage.promptChars).toBe(5000);
      expect(guard.currentUsage.llmCalls).toBe(2);
    });
  });

  describe('getDowngradeAction', () => {
    it('returns null when not over budget', () => {
      expect(guard.getDowngradeAction()).toBeNull();
    });

    it('returns downgrades in order when over budget', () => {
      guard.recordLlmCall(1000);
      guard.recordLlmCall(1000);
      // Now over LLM budget

      expect(guard.getDowngradeAction()).toBe('trim_dom');
      expect(guard.getDowngradeAction()).toBe('drop_history');
      expect(guard.getDowngradeAction()).toBe('observe_scope_narrow');
      expect(guard.getDowngradeAction()).toBe('require_human_checkpoint');
    });

    it('returns null after all downgrades exhausted', () => {
      guard.recordLlmCall(1000);
      guard.recordLlmCall(1000);

      guard.getDowngradeAction(); // trim_dom
      guard.getDowngradeAction(); // drop_history
      guard.getDowngradeAction(); // observe_scope_narrow
      guard.getDowngradeAction(); // require_human_checkpoint

      expect(guard.getDowngradeAction()).toBeNull();
    });
  });

  describe('isOverBudget', () => {
    it('returns false initially', () => {
      expect(guard.isOverBudget()).toBe(false);
    });

    it('returns true when LLM calls exceeded', () => {
      guard.recordLlmCall(100);
      guard.recordLlmCall(100);
      expect(guard.isOverBudget()).toBe(true);
    });

    it('returns true when authoring calls exceeded', () => {
      guard.recordAuthoringCall();
      guard.recordAuthoringCall();
      expect(guard.isOverBudget()).toBe(true);
    });

    it('returns true when prompt chars exceeded', () => {
      guard.recordLlmCall(6000);
      expect(guard.isOverBudget()).toBe(true);
    });
  });

  describe('getters', () => {
    it('returns max DOM snippet chars', () => {
      expect(guard.getMaxDomSnippetChars()).toBe(2500);
    });

    it('returns authoring timeout', () => {
      expect(guard.getAuthoringTimeoutMs()).toBe(12000);
    });

    it('returns budget config', () => {
      expect(guard.budget.maxLlmCallsPerRun).toBe(2);
    });
  });

  describe('reset', () => {
    it('resets all usage counters', () => {
      guard.recordLlmCall(3000);
      guard.recordAuthoringCall();
      guard.recordScreenshot();

      guard.reset();

      expect(guard.currentUsage).toEqual({
        llmCalls: 0,
        authoringCalls: 0,
        promptChars: 0,
        screenshots: 0,
      });
      expect(guard.canCallLlm()).toBe(true);
      expect(guard.canCallAuthoring()).toBe(true);
    });

    it('resets downgrade index', () => {
      guard.recordLlmCall(1000);
      guard.recordLlmCall(1000);
      guard.getDowngradeAction(); // trim_dom

      guard.reset();
      guard.recordLlmCall(1000);
      guard.recordLlmCall(1000);

      expect(guard.getDowngradeAction()).toBe('trim_dom');
    });
  });
});
