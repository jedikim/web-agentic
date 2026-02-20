import type {
  WorkflowStep,
  RunContext,
  StepResult,
  ActionRef,
} from '../types/index.js';
import type { BrowserEngine } from '../engines/browser-engine.js';
import type { HealingMemory } from '../memory/healing-memory.js';
import type { BudgetGuard } from './budget-guard.js';
import type { CheckpointHandler } from './checkpoint.js';
import type { RecoveryPipeline, RecoveryResult } from './recovery-pipeline.js';
import type { CanvasDetector, DetectorPage } from '../engines/canvas-detector.js';
import { validateExpectations } from './validator.js';
import { interpolate, interpolateStep } from '../recipe/template.js';
import { classifyError } from '../exception/classifier.js';
import { createRecoveryPlan } from '../exception/router.js';
import { PlaywrightFallbackEngine } from '../engines/playwright-fallback.js';

export interface AuthoringClient {
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
  }): Promise<{ patch: unknown[]; reason: string }>;
}

export class StepExecutor {
  private recoveryPipeline: RecoveryPipeline | null = null;
  private canvasDetector: CanvasDetector | null = null;
  private detectorPage: DetectorPage | null = null;

  constructor(
    private stagehand: BrowserEngine,
    private playwright: BrowserEngine,
    private healingMemory: HealingMemory,
    private authoringClient: AuthoringClient | null,
    private budgetGuard: BudgetGuard,
    private checkpoint: CheckpointHandler,
  ) {}

  /**
   * Set the recovery pipeline for structured recovery on step failures.
   * When set, the execute method will use the pipeline instead of inline fallbacks.
   */
  setRecoveryPipeline(pipeline: RecoveryPipeline): void {
    this.recoveryPipeline = pipeline;
  }

  /**
   * Set the canvas detector for surface type detection during failure analysis.
   * When set, CanvasDetected errors are detected automatically before routing.
   */
  setCanvasDetector(detector: CanvasDetector, page: DetectorPage): void {
    this.canvasDetector = detector;
    this.detectorPage = page;
  }

  /**
   * Get the last recovery result (if any) from the most recent execute call.
   */
  get lastRecoveryResult(): RecoveryResult | null {
    return this._lastRecoveryResult;
  }
  private _lastRecoveryResult: RecoveryResult | null = null;

  async execute(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    const start = Date.now();
    const resolvedStep = interpolateStep(step, context.vars);
    this._lastRecoveryResult = null;

    try {
      const result = await this.executeOp(resolvedStep, context);
      const durationMs = Date.now() - start;

      if (result.ok && resolvedStep.expect) {
        const validation = await validateExpectations(resolvedStep.expect, this.stagehand);
        if (!validation.ok) {
          const failResult: StepResult = {
            stepId: step.id,
            ok: false,
            errorType: 'ExpectationFailed',
            message: `Expectations failed: ${validation.failures.map((f) => `${f.expectation.kind}=${f.expectation.value}`).join(', ')}`,
            durationMs,
          };

          // Try recovery pipeline for expectation failure
          if (this.recoveryPipeline && failResult.errorType) {
            const recovered = await this.tryRecoveryPipeline(failResult, resolvedStep, context);
            if (recovered) {
              return { ...recovered, durationMs: Date.now() - start };
            }
          }

          return failResult;
        }
      }

      // If step failed and recovery pipeline is available, try it
      if (!result.ok && result.errorType && this.recoveryPipeline) {
        const recovered = await this.tryRecoveryPipeline(result, resolvedStep, context);
        if (recovered) {
          return { ...recovered, durationMs: Date.now() - start };
        }
      }

      return { ...result, durationMs };
    } catch (error) {
      const durationMs = Date.now() - start;
      const errorType = classifyError(error, {
        selector: resolvedStep.targetKey,
        url: await this.stagehand.currentUrl().catch(() => ''),
      });
      const failResult: StepResult = {
        stepId: step.id,
        ok: false,
        errorType,
        message: error instanceof Error ? error.message : String(error),
        durationMs,
      };

      // Try recovery pipeline for caught errors
      if (this.recoveryPipeline && errorType) {
        const recovered = await this.tryRecoveryPipeline(failResult, resolvedStep, context);
        if (recovered) {
          return { ...recovered, durationMs: Date.now() - start };
        }
      }

      return failResult;
    }
  }

  /**
   * Attempt recovery using the RecoveryPipeline.
   * Creates a RecoveryPlan from the error type and context, then runs the pipeline.
   */
  private async tryRecoveryPipeline(
    failResult: StepResult,
    step: WorkflowStep,
    context: RunContext,
  ): Promise<StepResult | null> {
    if (!this.recoveryPipeline || !failResult.errorType) return null;

    try {
      const url = await this.stagehand.currentUrl().catch(() => '');
      const title = await this.stagehand.currentTitle().catch(() => '');
      const actionEntry = step.targetKey ? context.recipe.actions[step.targetKey] : undefined;

      // Canvas detection: check if failure is due to a non-DOM surface
      let errorType = failResult.errorType;
      if (
        this.canvasDetector &&
        this.detectorPage &&
        errorType !== 'CanvasDetected' &&
        errorType !== 'CaptchaOr2FA' &&
        errorType !== 'AuthoringServiceTimeout'
      ) {
        try {
          const surface = await this.canvasDetector.detect(this.detectorPage, step.targetKey);
          if (surface.type !== 'standard') {
            errorType = 'CanvasDetected';
          }
        } catch {
          // Canvas detection failed — use original error type
        }
      }

      const plan = createRecoveryPlan(errorType, {
        stepId: step.id,
        url,
        title,
        failedSelector: step.targetKey,
        failedAction: actionEntry?.preferred,
      });

      const result = await this.recoveryPipeline.recover(plan, context.recipe, context.runId);
      this._lastRecoveryResult = result;

      if (result.recovered) {
        return {
          stepId: step.id,
          ok: true,
          message: `Recovered via ${result.method}`,
        };
      }
    } catch {
      // Recovery pipeline failed entirely
    }

    return null;
  }

  private async executeOp(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    switch (step.op) {
      case 'goto':
        return this.executeGoto(step);
      case 'act_cached':
        return this.executeActCached(step, context);
      case 'act_template':
        return this.executeActTemplate(step, context);
      case 'extract':
        return this.executeExtract(step, context);
      case 'choose':
        return this.executeChoose(step, context);
      case 'checkpoint':
        return this.executeCheckpoint(step);
      case 'wait':
        return this.executeWait(step);
      default:
        return { stepId: step.id, ok: false, errorType: 'ExpectationFailed', message: `Unknown op: ${step.op}` };
    }
  }

  private async executeGoto(step: WorkflowStep): Promise<StepResult> {
    const url = step.args?.url as string;
    if (!url) return { stepId: step.id, ok: false, message: 'goto requires args.url' };

    await this.stagehand.goto(url);
    return { stepId: step.id, ok: true };
  }

  /**
   * Implements the 6-level fallback ladder (Blueprint section 7.1):
   * 1. act(cached action) from actions.json
   * 2. Playwright strict locator fallback from selectors.json
   * 3. observe(scope) re-discovery
   * 4. Healing memory match
   * 5. Authoring service /plan-patch
   * 6. Screenshot checkpoint (GO/NOT GO)
   */
  private async executeActCached(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    const targetKey = step.targetKey;
    if (!targetKey) return { stepId: step.id, ok: false, message: 'act_cached requires targetKey' };

    const actionEntry = context.recipe.actions[targetKey];

    // Level 1: act(cached action)
    if (actionEntry) {
      try {
        const ok = await this.stagehand.act(actionEntry.preferred);
        if (ok) {
          return { stepId: step.id, ok: true };
        }
      } catch {
        // Fall through to level 2
      }
    }

    // Level 2: Playwright strict locator fallback
    const selectorEntry = context.recipe.selectors[targetKey];
    if (selectorEntry && this.playwright instanceof PlaywrightFallbackEngine) {
      try {
        const action: ActionRef = actionEntry?.preferred ?? {
          selector: selectorEntry.primary,
          description: targetKey,
          method: 'click',
        };
        const ok = await this.playwright.actWithFallback(action, selectorEntry);
        if (ok) {
          return { stepId: step.id, ok: true };
        }
      } catch {
        // Fall through to level 3
      }
    }

    // Level 3: observe(scope) re-discovery
    if (this.budgetGuard.canCallLlm()) {
      try {
        const instruction = actionEntry?.instruction ?? `find and interact with ${targetKey}`;
        const candidates = await this.stagehand.observe(instruction);
        this.budgetGuard.recordLlmCall(instruction.length);

        if (candidates.length > 0) {
          const ok = await this.stagehand.act(candidates[0]);
          if (ok) {
            // Record success for healing memory
            const url = await this.stagehand.currentUrl();
            await this.healingMemory.record(targetKey, candidates[0], url, {
              originalSelector: actionEntry?.preferred?.selector ?? '',
              healedSelector: candidates[0].selector,
              domContext: '',
              pageTitle: await this.stagehand.currentTitle().catch(() => ''),
              pageUrl: url,
              method: 'observe_refresh',
              timestamp: new Date().toISOString(),
            });
            return { stepId: step.id, ok: true };
          }
        }
      } catch {
        // Fall through to level 4
      }
    }

    // Level 4: Healing memory match
    try {
      const url = await this.stagehand.currentUrl();
      const healedAction = await this.healingMemory.findMatch(targetKey, url);
      if (healedAction) {
        const ok = await this.stagehand.act(healedAction);
        if (ok) {
          return { stepId: step.id, ok: true };
        }
      }
    } catch {
      // Fall through to level 5
    }

    // Level 5: Authoring service /plan-patch
    if (this.authoringClient && this.budgetGuard.canCallAuthoring()) {
      try {
        const url = await this.stagehand.currentUrl();
        const title = await this.stagehand.currentTitle();
        this.budgetGuard.recordAuthoringCall();

        await this.authoringClient.planPatch({
          requestId: `${context.runId}-${step.id}`,
          stepId: step.id,
          errorType: 'TargetNotFound',
          url,
          title,
          failedSelector: actionEntry?.preferred.selector ?? selectorEntry?.primary,
          failedAction: actionEntry?.preferred as unknown as Record<string, unknown>,
        });

        // Patch is applied by the runner, not here. Signal that patch was requested.
        return {
          stepId: step.id,
          ok: false,
          errorType: 'TargetNotFound',
          message: 'Authoring service patch requested',
        };
      } catch {
        // Fall through to level 6
      }
    }

    // Level 6: Screenshot checkpoint
    return this.screenshotCheckpoint(step);
  }

  private async executeActTemplate(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    const targetKey = step.targetKey;
    if (!targetKey) return { stepId: step.id, ok: false, message: 'act_template requires targetKey' };

    const actionEntry = context.recipe.actions[targetKey];
    if (!actionEntry) {
      return { stepId: step.id, ok: false, errorType: 'TargetNotFound', message: `No action found for ${targetKey}` };
    }

    const action: ActionRef = {
      ...actionEntry.preferred,
      arguments: actionEntry.preferred.arguments?.map((a) => {
        if (typeof a === 'string' && a.includes('{{')) {
          return interpolate(a, context.vars);
        }
        return a;
      }),
    };

    const ok = await this.stagehand.act(action);
    return { stepId: step.id, ok };
  }

  private async executeExtract(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    const targetKey = step.targetKey;
    const schema = step.args?.schema;
    const scope = step.args?.scope as string | undefined;
    const into = step.args?.into as string | undefined;

    try {
      const data = await this.stagehand.extract(schema ?? { type: 'object' }, scope);
      if (into) {
        context.vars[into] = data;
      }
      return { stepId: step.id, ok: true, data: { [into ?? 'extracted']: data } };
    } catch (error) {
      return {
        stepId: step.id,
        ok: false,
        errorType: 'ExtractionEmpty',
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }

  private async executeChoose(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    const from = step.args?.from as string;
    const policyKey = step.args?.policy as string;
    const into = step.args?.into as string;

    if (!from || !policyKey || !into) {
      return { stepId: step.id, ok: false, message: 'choose requires args: from, policy, into' };
    }

    const candidates = context.vars[from];
    const policy = context.recipe.policies[policyKey];

    if (!Array.isArray(candidates)) {
      return { stepId: step.id, ok: false, message: `"${from}" is not an array` };
    }

    if (!policy) {
      return { stepId: step.id, ok: false, message: `Policy "${policyKey}" not found` };
    }

    const { evaluatePolicy } = await import('../engines/policy-engine.js');
    const chosen = evaluatePolicy(candidates as Record<string, unknown>[], policy);

    if (!chosen) {
      return { stepId: step.id, ok: false, message: 'No candidate passed policy' };
    }

    context.vars[into] = chosen;
    return { stepId: step.id, ok: true, data: { [into]: chosen } };
  }

  private async executeCheckpoint(step: WorkflowStep): Promise<StepResult> {
    const message = (step.args?.message as string) ?? 'Checkpoint: proceed?';

    let screenshot: Buffer | undefined;
    if (this.budgetGuard.canTakeScreenshot(true)) {
      try {
        screenshot = await this.stagehand.screenshot();
        this.budgetGuard.recordScreenshot();
      } catch {
        // Continue without screenshot
      }
    }

    const decision = await this.checkpoint.requestApproval(message, screenshot);
    if (decision === 'NOT_GO') {
      return { stepId: step.id, ok: false, message: 'Checkpoint: NOT GO' };
    }
    return { stepId: step.id, ok: true };
  }

  private async executeWait(step: WorkflowStep): Promise<StepResult> {
    const ms = (step.args?.ms as number) ?? 1000;
    await new Promise((resolve) => setTimeout(resolve, ms));
    return { stepId: step.id, ok: true };
  }

  private async screenshotCheckpoint(step: WorkflowStep): Promise<StepResult> {
    let screenshot: Buffer | undefined;
    if (this.budgetGuard.canTakeScreenshot(false)) {
      try {
        screenshot = await this.stagehand.screenshot();
        this.budgetGuard.recordScreenshot();
      } catch {
        // No screenshot available
      }
    }

    const decision = await this.checkpoint.requestApproval(
      `Step "${step.id}" failed all recovery levels. Review and decide.`,
      screenshot,
    );

    if (decision === 'GO') {
      return { stepId: step.id, ok: true, message: 'Resolved via checkpoint GO' };
    }

    return {
      stepId: step.id,
      ok: false,
      errorType: 'TargetNotFound',
      message: 'All fallback levels exhausted. Checkpoint NOT GO.',
    };
  }
}
