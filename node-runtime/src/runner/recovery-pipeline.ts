import type {
  ActionRef,
  ErrorType,
  PatchPayload,
  Recipe,
} from '../types/index.js';
import type { RecoveryAction } from '../exception/router.js';
import type { ObserveRefresher } from '../engines/observe-refresher.js';
import type { HealingMemory } from '../memory/healing-memory.js';
import type { BudgetGuard } from './budget-guard.js';
import type { CheckpointHandler } from './checkpoint.js';
import type { BrowserEngine } from '../engines/browser-engine.js';
import type { PlaywrightFallbackEngine } from '../engines/playwright-fallback.js';
import type { PlanPatchResponse } from '../authoring-client/plan-patch.js';

export interface AuthoringClientForRecovery {
  planPatch(request: {
    requestId: string;
    stepId: string;
    errorType: string;
    url: string;
    title?: string;
    failedSelector?: string;
    failedAction?: Record<string, unknown>;
    domSnippet?: string;
    screenshotBase64?: string;
  }): Promise<PlanPatchResponse>;
}

export interface FailureContext {
  stepId: string;
  errorType: ErrorType;
  url: string;
  title: string;
  failedSelector?: string;
  failedAction?: ActionRef;
  domSnippet?: string;
  screenshotPath?: string;
}

export interface RecoveryPlan {
  actions: RecoveryAction[];
  context: FailureContext;
}

export interface RecoveryResult {
  recovered: boolean;
  action?: ActionRef;
  patchApplied?: PatchPayload;
  method: string;
}

/**
 * RecoveryPipeline orchestrates the full fallback ladder from Blueprint section 7.1.
 * Tries each recovery action in order until one succeeds or all are exhausted.
 */
export class RecoveryPipeline {
  constructor(
    private observeRefresher: ObserveRefresher,
    private healingMemory: HealingMemory,
    private authoringClient: AuthoringClientForRecovery | null,
    private budgetGuard: BudgetGuard,
    private checkpointHandler: CheckpointHandler,
    private stagehand: BrowserEngine,
    private playwright: PlaywrightFallbackEngine | null,
  ) {}

  /**
   * Execute recovery actions in order until one succeeds.
   * Returns the recovered ActionRef or indicates failure.
   */
  async recover(plan: RecoveryPlan, recipe: Recipe, runId: string): Promise<RecoveryResult> {
    let lastResult: RecoveryResult = { recovered: false, method: 'none' };

    for (const action of plan.actions) {
      try {
        const result = await this.executeAction(action, plan.context, recipe, runId);
        lastResult = result;

        if (result.recovered) {
          return result;
        }

        // Terminal actions: stop the ladder even if not recovered
        if (action === 'abort' || action === 'checkpoint') {
          return result;
        }
      } catch {
        // Action threw — continue to next
      }
    }

    return lastResult;
  }

  private async executeAction(
    action: RecoveryAction,
    context: FailureContext,
    recipe: Recipe,
    runId: string,
  ): Promise<RecoveryResult> {
    switch (action) {
      case 'retry':
        return this.executeRetry(context, recipe);

      case 'observe_refresh':
        return this.executeObserveRefresh(context, recipe);

      case 'selector_fallback':
        return this.executeSelectorFallback(context, recipe);

      case 'healing_memory':
        return this.executeHealingMemory(context);

      case 'authoring_patch':
        return this.executeAuthoringPatch(context, runId);

      case 'checkpoint':
        return this.executeCheckpoint(context);

      case 'abort':
        return { recovered: false, method: 'abort' };

      default:
        return { recovered: false, method: 'unknown' };
    }
  }

  private async executeRetry(
    context: FailureContext,
    recipe: Recipe,
  ): Promise<RecoveryResult> {
    if (!context.failedAction) {
      return { recovered: false, method: 'retry' };
    }

    const ok = await this.stagehand.act(context.failedAction);
    if (ok) {
      return { recovered: true, action: context.failedAction, method: 'retry' };
    }
    return { recovered: false, method: 'retry' };
  }

  private async executeObserveRefresh(
    context: FailureContext,
    recipe: Recipe,
  ): Promise<RecoveryResult> {
    if (!this.budgetGuard.canCallLlm()) {
      return { recovered: false, method: 'observe_refresh' };
    }

    const targetKey = context.failedSelector ?? context.stepId;
    const actionEntry = recipe.actions[targetKey];
    const instruction = actionEntry?.instruction ?? `find and interact with ${targetKey}`;

    const refreshed = await this.observeRefresher.refresh(targetKey, instruction);
    this.budgetGuard.recordLlmCall(instruction.length);

    if (refreshed) {
      const ok = await this.stagehand.act(refreshed);
      if (ok) {
        // Record in healing memory for future use
        await this.healingMemory.record(targetKey, refreshed, context.url);
        return { recovered: true, action: refreshed, method: 'observe_refresh' };
      }
    }

    return { recovered: false, method: 'observe_refresh' };
  }

  private async executeSelectorFallback(
    context: FailureContext,
    recipe: Recipe,
  ): Promise<RecoveryResult> {
    if (!this.playwright) {
      return { recovered: false, method: 'selector_fallback' };
    }

    const targetKey = context.failedSelector ?? context.stepId;
    const selectorEntry = recipe.selectors[targetKey];

    if (!selectorEntry) {
      return { recovered: false, method: 'selector_fallback' };
    }

    const actionRef: ActionRef = context.failedAction ?? {
      selector: selectorEntry.primary,
      description: targetKey,
      method: 'click',
    };

    const ok = await this.playwright.actWithFallback(actionRef, selectorEntry);
    if (ok) {
      return { recovered: true, action: actionRef, method: 'selector_fallback' };
    }

    return { recovered: false, method: 'selector_fallback' };
  }

  private async executeHealingMemory(
    context: FailureContext,
  ): Promise<RecoveryResult> {
    const targetKey = context.failedSelector ?? context.stepId;
    const healedAction = await this.healingMemory.findMatch(targetKey, context.url);

    if (healedAction) {
      const ok = await this.stagehand.act(healedAction);
      if (ok) {
        return { recovered: true, action: healedAction, method: 'healing_memory' };
      }
    }

    return { recovered: false, method: 'healing_memory' };
  }

  private async executeAuthoringPatch(
    context: FailureContext,
    runId: string,
  ): Promise<RecoveryResult> {
    if (!this.authoringClient) {
      return { recovered: false, method: 'authoring_patch' };
    }

    if (!this.budgetGuard.canCallAuthoring()) {
      return { recovered: false, method: 'authoring_patch' };
    }

    this.budgetGuard.recordAuthoringCall();

    const response = await this.authoringClient.planPatch({
      requestId: `${runId}-${context.stepId}-recovery`,
      stepId: context.stepId,
      errorType: context.errorType,
      url: context.url,
      title: context.title,
      failedSelector: context.failedSelector,
      failedAction: context.failedAction as unknown as Record<string, unknown>,
      domSnippet: context.domSnippet,
    });

    const patchPayload: PatchPayload = {
      patch: response.patch as PatchPayload['patch'],
      reason: response.reason,
    };

    return {
      recovered: true,
      patchApplied: patchPayload,
      method: 'authoring_patch',
    };
  }

  private async executeCheckpoint(
    context: FailureContext,
  ): Promise<RecoveryResult> {
    let screenshot: Buffer | undefined;
    if (this.budgetGuard.canTakeScreenshot(false)) {
      try {
        screenshot = await this.stagehand.screenshot();
        this.budgetGuard.recordScreenshot();
      } catch {
        // No screenshot available
      }
    }

    const decision = await this.checkpointHandler.requestApproval(
      `Step "${context.stepId}" failed (${context.errorType}). All automated recovery exhausted. Review and decide.`,
      screenshot,
    );

    if (decision === 'GO') {
      return { recovered: true, method: 'checkpoint' };
    }

    return { recovered: false, method: 'checkpoint' };
  }
}
