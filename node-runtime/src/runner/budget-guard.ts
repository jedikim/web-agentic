import type {
  BudgetConfig,
  BudgetUsage,
  DowngradeAction,
  TokenBudget,
} from '../types/budget.js';

export class BudgetGuard {
  private usage: BudgetUsage;
  private downgradeIndex: number;

  constructor(private config: BudgetConfig) {
    this.usage = {
      llmCalls: 0,
      authoringCalls: 0,
      promptChars: 0,
      screenshots: 0,
    };
    this.downgradeIndex = 0;
  }

  get budget(): TokenBudget {
    return this.config.budget;
  }

  get currentUsage(): BudgetUsage {
    return { ...this.usage };
  }

  canCallLlm(): boolean {
    return this.usage.llmCalls < this.config.budget.maxLlmCallsPerRun;
  }

  canCallAuthoring(): boolean {
    return this.usage.authoringCalls < this.config.budget.maxAuthoringServiceCallsPerRun;
  }

  canTakeScreenshot(isCheckpoint: boolean): boolean {
    if (isCheckpoint) {
      return this.usage.screenshots < this.config.budget.maxScreenshotPerCheckpoint;
    }
    return this.usage.screenshots < this.config.budget.maxScreenshotPerFailure;
  }

  recordLlmCall(promptChars: number): void {
    this.usage.llmCalls++;
    this.usage.promptChars += promptChars;
  }

  recordAuthoringCall(): void {
    this.usage.authoringCalls++;
  }

  recordScreenshot(): void {
    this.usage.screenshots++;
  }

  /**
   * Returns the next downgrade action if budget thresholds are exceeded,
   * or null if no downgrade is needed or all downgrades have been applied.
   *
   * Downgrade order from config: trim_dom -> drop_history -> observe_scope_narrow -> require_human_checkpoint
   */
  getDowngradeAction(): DowngradeAction | null {
    if (!this.isOverBudget()) {
      return null;
    }

    if (this.downgradeIndex >= this.config.downgradeOrder.length) {
      return null;
    }

    const action = this.config.downgradeOrder[this.downgradeIndex];
    this.downgradeIndex++;
    return action;
  }

  /**
   * Check if any budget threshold is exceeded.
   */
  isOverBudget(): boolean {
    const b = this.config.budget;
    return (
      this.usage.llmCalls >= b.maxLlmCallsPerRun ||
      this.usage.authoringCalls >= b.maxAuthoringServiceCallsPerRun ||
      this.usage.promptChars >= b.maxPromptChars
    );
  }

  /**
   * Get the maximum allowed DOM snippet characters, considering any trim_dom downgrade.
   */
  getMaxDomSnippetChars(): number {
    return this.config.budget.maxDomSnippetChars;
  }

  /**
   * Get the authoring service timeout in ms.
   */
  getAuthoringTimeoutMs(): number {
    return this.config.budget.authoringServiceTimeoutMs;
  }

  /**
   * Reset usage counters (for a new run).
   */
  reset(): void {
    this.usage = {
      llmCalls: 0,
      authoringCalls: 0,
      promptChars: 0,
      screenshots: 0,
    };
    this.downgradeIndex = 0;
  }
}
