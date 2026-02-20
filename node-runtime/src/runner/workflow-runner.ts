import type {
  RunContext,
  StepResult,
  WorkflowStep,
  Fingerprint,
} from '../types/index.js';
import type { BrowserEngine } from '../engines/browser-engine.js';
import type { CheckpointHandler } from './checkpoint.js';
import { StepExecutor } from './step-executor.js';

export interface RunResult {
  ok: boolean;
  stepResults: StepResult[];
  patchApplied: boolean;
  abortedAt?: string;
  durationMs: number;
}

export class WorkflowRunner {
  private stepExecutor: StepExecutor;

  constructor(
    private stagehand: BrowserEngine,
    private playwright: BrowserEngine,
    stepExecutor: StepExecutor,
    private checkpoint: CheckpointHandler,
  ) {
    this.stepExecutor = stepExecutor;
  }

  async run(context: RunContext): Promise<RunResult> {
    const start = Date.now();
    const stepResults: StepResult[] = [];
    let patchApplied = false;

    // 1. Preflight: validate fingerprints
    const preflightOk = await this.preflight(context);
    if (!preflightOk) {
      return {
        ok: false,
        stepResults,
        patchApplied: false,
        abortedAt: 'preflight',
        durationMs: Date.now() - start,
      };
    }

    // 2. Request GO/NOT GO
    const goDecision = await this.checkpoint.requestApproval(
      `Ready to execute workflow "${context.recipe.workflow.id}" (${context.recipe.workflow.steps.length} steps). Proceed?`,
    );

    if (goDecision === 'NOT_GO') {
      return {
        ok: false,
        stepResults,
        patchApplied: false,
        abortedAt: 'go_not_go',
        durationMs: Date.now() - start,
      };
    }

    // 3. Execute steps
    const steps = context.recipe.workflow.steps;
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const result = await this.executeStepWithRetry(step, context);
      stepResults.push(result);

      if (!result.ok) {
        const onFail = step.onFail ?? 'fallback';

        if (onFail === 'abort') {
          return {
            ok: false,
            stepResults,
            patchApplied,
            abortedAt: step.id,
            durationMs: Date.now() - start,
          };
        }

        if (onFail === 'checkpoint') {
          const decision = await this.checkpoint.requestApproval(
            `Step "${step.id}" failed: ${result.message ?? result.errorType}. Continue?`,
          );

          if (decision === 'NOT_GO') {
            return {
              ok: false,
              stepResults,
              patchApplied,
              abortedAt: step.id,
              durationMs: Date.now() - start,
            };
          }
          // GO: continue to next step
          continue;
        }

        // 'retry' and 'fallback' are handled inside step-executor
        // If we reach here and result is still not ok, treat as failure
        if (onFail === 'fallback' || onFail === 'retry') {
          // The step executor already handled the fallback ladder
          // If still failed, abort the run
          return {
            ok: false,
            stepResults,
            patchApplied,
            abortedAt: step.id,
            durationMs: Date.now() - start,
          };
        }
      }
    }

    return {
      ok: true,
      stepResults,
      patchApplied,
      durationMs: Date.now() - start,
    };
  }

  private async preflight(context: RunContext): Promise<boolean> {
    const fingerprints = context.recipe.fingerprints;
    if (Object.keys(fingerprints).length === 0) return true;

    try {
      const url = await this.stagehand.currentUrl();

      for (const [_key, fp] of Object.entries(fingerprints)) {
        if (!this.checkFingerprint(fp, url)) {
          return false;
        }
      }
      return true;
    } catch {
      // If we can't even check, allow through (fingerprints are optional guards)
      return true;
    }
  }

  private checkFingerprint(fp: Fingerprint, currentUrl: string): boolean {
    if (fp.urlContains && !currentUrl.includes(fp.urlContains)) {
      return false;
    }
    // mustText and mustSelectors require page content - skipped in preflight
    // since we may not be on the right page yet
    return true;
  }

  private async executeStepWithRetry(
    step: WorkflowStep,
    context: RunContext,
    maxRetries: number = 1,
  ): Promise<StepResult> {
    let lastResult: StepResult | null = null;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const result = await this.stepExecutor.execute(step, context);
      if (result.ok) return result;
      lastResult = result;

      if (step.onFail !== 'retry' && attempt > 0) break;
    }

    return lastResult!;
  }
}
