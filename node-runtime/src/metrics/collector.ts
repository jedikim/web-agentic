import type { StepResult } from '../types/index.js';

export interface RunMetrics {
  runId: string;
  flow: string;
  version: string;
  startedAt: string;
  completedAt: string;
  success: boolean;
  durationMs: number;
  llmCalls: number;
  tokenUsage: { prompt: number; completion: number };
  patchCount: number;
  patchSuccessRate: number;
  healingMemoryHits: number;
  healingMemoryMisses: number;
  checkpointWaitMs: number;
  stepResults: { total: number; passed: number; failed: number; recovered: number };
  fallbackLadderUsage: Record<string, number>;
}

export class MetricsCollector {
  private runId = '';
  private flow = '';
  private version = '';
  private startedAt = '';
  private llmCalls = 0;
  private tokenUsage = { prompt: 0, completion: 0 };
  private patchTotal = 0;
  private patchSuccess = 0;
  private healingHits = 0;
  private healingMisses = 0;
  private checkpointWaitMs = 0;
  private stepTotal = 0;
  private stepPassed = 0;
  private stepFailed = 0;
  private stepRecovered = 0;
  private fallbackLadderUsage: Record<string, number> = {};

  startRun(runId: string, flow: string, version: string): void {
    this.runId = runId;
    this.flow = flow;
    this.version = version;
    this.startedAt = new Date().toISOString();
    this.llmCalls = 0;
    this.tokenUsage = { prompt: 0, completion: 0 };
    this.patchTotal = 0;
    this.patchSuccess = 0;
    this.healingHits = 0;
    this.healingMisses = 0;
    this.checkpointWaitMs = 0;
    this.stepTotal = 0;
    this.stepPassed = 0;
    this.stepFailed = 0;
    this.stepRecovered = 0;
    this.fallbackLadderUsage = {};
  }

  recordStep(result: StepResult, recoveryMethod?: string): void {
    this.stepTotal++;
    if (result.ok) {
      if (recoveryMethod) {
        this.stepRecovered++;
        this.fallbackLadderUsage[recoveryMethod] =
          (this.fallbackLadderUsage[recoveryMethod] ?? 0) + 1;
      } else {
        this.stepPassed++;
      }
    } else {
      this.stepFailed++;
    }
  }

  recordLlmCall(tokens: { prompt: number; completion: number }): void {
    this.llmCalls++;
    this.tokenUsage.prompt += tokens.prompt;
    this.tokenUsage.completion += tokens.completion;
  }

  recordPatch(success: boolean): void {
    this.patchTotal++;
    if (success) this.patchSuccess++;
  }

  recordHealingMemory(hit: boolean): void {
    if (hit) {
      this.healingHits++;
    } else {
      this.healingMisses++;
    }
  }

  recordCheckpointWait(waitMs: number): void {
    this.checkpointWaitMs += waitMs;
  }

  finalize(success: boolean): RunMetrics {
    return {
      runId: this.runId,
      flow: this.flow,
      version: this.version,
      startedAt: this.startedAt,
      completedAt: new Date().toISOString(),
      success,
      durationMs: Date.now() - new Date(this.startedAt).getTime(),
      llmCalls: this.llmCalls,
      tokenUsage: { ...this.tokenUsage },
      patchCount: this.patchTotal,
      patchSuccessRate: this.patchTotal > 0 ? this.patchSuccess / this.patchTotal : 0,
      healingMemoryHits: this.healingHits,
      healingMemoryMisses: this.healingMisses,
      checkpointWaitMs: this.checkpointWaitMs,
      stepResults: {
        total: this.stepTotal,
        passed: this.stepPassed,
        failed: this.stepFailed,
        recovered: this.stepRecovered,
      },
      fallbackLadderUsage: { ...this.fallbackLadderUsage },
    };
  }
}
