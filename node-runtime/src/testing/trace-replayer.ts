import { readFile } from 'node:fs/promises';
import type { BrowserEngine } from '../engines/browser-engine.js';
import type { StepResult } from '../types/step-result.js';
import type { StructuredTraceBundle, TraceStep } from '../logging/trace-bundler.js';

export interface StepDivergence {
  stepId: string;
  original: { ok: boolean; data?: unknown };
  replayed: { ok: boolean; data?: unknown };
  reason: string;
}

export interface ReplayResult {
  originalRunId: string;
  replayRunId: string;
  totalSteps: number;
  matchedSteps: number;
  divergedSteps: number;
  divergences: StepDivergence[];
  overallMatch: boolean;
}

/**
 * TraceReplayer loads a saved trace bundle and replays each step
 * against a live BrowserEngine, comparing results to detect regressions.
 */
export class TraceReplayer {
  /**
   * Load a trace bundle from a JSON file path.
   */
  async loadTrace(tracePath: string): Promise<StructuredTraceBundle> {
    const content = await readFile(tracePath, 'utf-8');
    return JSON.parse(content) as StructuredTraceBundle;
  }

  /**
   * Replay each step from the trace against the given engine.
   * Compares each replayed result with the original to detect divergences.
   */
  async replay(trace: StructuredTraceBundle, engine: BrowserEngine): Promise<ReplayResult> {
    const replayRunId = `replay-${Date.now()}`;
    const divergences: StepDivergence[] = [];
    let matchedSteps = 0;

    for (const step of trace.steps) {
      const replayed = await this.executeStep(step, engine);
      const divergence = this.compareStep(step, replayed);

      if (divergence) {
        divergences.push(divergence);
      } else {
        matchedSteps++;
      }
    }

    return {
      originalRunId: trace.runId,
      replayRunId,
      totalSteps: trace.steps.length,
      matchedSteps,
      divergedSteps: divergences.length,
      divergences,
      overallMatch: divergences.length === 0,
    };
  }

  /**
   * Compare an original trace step with a replayed result.
   * Returns a StepDivergence if they differ, or null if they match.
   */
  compareStep(original: TraceStep, replayed: StepResult): StepDivergence | null {
    // Primary check: ok status must match
    if (original.result.ok !== replayed.ok) {
      return {
        stepId: original.stepId,
        original: { ok: original.result.ok, data: original.result.data },
        replayed: { ok: replayed.ok, data: replayed.data },
        reason: original.result.ok
          ? `Step "${original.stepId}" passed originally but failed on replay: ${replayed.message ?? 'unknown error'}`
          : `Step "${original.stepId}" failed originally but passed on replay`,
      };
    }

    // If both failed, check if error types match
    if (!original.result.ok && !replayed.ok) {
      if (original.result.errorType !== replayed.errorType) {
        return {
          stepId: original.stepId,
          original: { ok: original.result.ok, data: original.result.data },
          replayed: { ok: replayed.ok, data: replayed.data },
          reason: `Step "${original.stepId}" error type changed from "${original.result.errorType}" to "${replayed.errorType}"`,
        };
      }
    }

    return null;
  }

  /**
   * Execute a single step against the engine based on the step's op type.
   */
  private async executeStep(step: TraceStep, engine: BrowserEngine): Promise<StepResult> {
    const startTime = Date.now();

    try {
      switch (step.op) {
        case 'goto': {
          const url = step.result.data?.url as string | undefined;
          if (url) {
            await engine.goto(url);
          }
          return {
            stepId: step.stepId,
            ok: true,
            durationMs: Date.now() - startTime,
          };
        }

        case 'act_cached':
        case 'act_template': {
          if (step.result.data?.action) {
            const action = step.result.data.action as {
              selector: string;
              description: string;
              method: string;
              arguments?: string[];
            };
            const success = await engine.act(action);
            return {
              stepId: step.stepId,
              ok: success,
              durationMs: Date.now() - startTime,
              errorType: success ? undefined : 'TargetNotFound',
              message: success ? undefined : 'Action failed during replay',
            };
          }
          // No action data saved, try using targetKey as instruction via observe
          if (step.targetKey) {
            const actions = await engine.observe(step.targetKey);
            if (actions.length > 0) {
              const success = await engine.act(actions[0]);
              return {
                stepId: step.stepId,
                ok: success,
                durationMs: Date.now() - startTime,
              };
            }
          }
          return {
            stepId: step.stepId,
            ok: false,
            durationMs: Date.now() - startTime,
            errorType: 'TargetNotFound',
            message: 'No action data available for replay',
          };
        }

        case 'extract': {
          const schema = step.result.data?.schema;
          const scope = step.result.data?.scope as string | undefined;
          const data = await engine.extract(schema ?? {}, scope);
          return {
            stepId: step.stepId,
            ok: true,
            data: { extracted: data },
            durationMs: Date.now() - startTime,
          };
        }

        case 'checkpoint':
        case 'choose':
        case 'wait': {
          // Non-browser steps: auto-pass during replay
          return {
            stepId: step.stepId,
            ok: true,
            durationMs: Date.now() - startTime,
          };
        }

        default: {
          return {
            stepId: step.stepId,
            ok: true,
            durationMs: Date.now() - startTime,
            message: `Unknown op "${step.op}" - skipped during replay`,
          };
        }
      }
    } catch (error) {
      return {
        stepId: step.stepId,
        ok: false,
        durationMs: Date.now() - startTime,
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }
}
