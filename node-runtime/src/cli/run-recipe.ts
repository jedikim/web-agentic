/**
 * CLI: Run a recipe from stdin JSON → JSONL events on stdout.
 *
 * Usage: echo '{"recipe":...}' | npx tsx node-runtime/src/cli/run-recipe.ts
 *
 * Reads a full recipe JSON object from stdin, launches a headless Playwright
 * browser, executes each workflow step, and emits JSONL progress events to
 * stdout so an upstream process (Python SSE proxy) can stream them to the UI.
 */

import { chromium } from 'playwright';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdtemp } from 'node:fs/promises';

import { PlaywrightFallbackEngine } from '../engines/playwright-fallback.js';
import { StepExecutor } from '../runner/step-executor.js';
import { AutoApproveCheckpointHandler } from '../runner/checkpoint.js';
import { BudgetGuard } from '../runner/budget-guard.js';
import { HealingMemory } from '../memory/healing-memory.js';
import { ObserveRefresher } from '../engines/observe-refresher.js';
import { RecoveryPipeline } from '../runner/recovery-pipeline.js';
import type { Recipe, RunContext, TokenBudget } from '../types/index.js';

// ── helpers ────────────────────────────────────────

function emit(event: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(event) + '\n');
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString('utf-8');
}

// ── main ───────────────────────────────────────────

const DEFAULT_BUDGET: TokenBudget = {
  maxLlmCallsPerRun: 10,
  maxPromptChars: 50_000,
  maxDomSnippetChars: 5000,
  maxScreenshotPerFailure: 3,
  maxScreenshotPerCheckpoint: 3,
  maxAuthoringServiceCallsPerRun: 3,
  authoringServiceTimeoutMs: 10_000,
};

async function main() {
  // 1. Read recipe from stdin
  const raw = await readStdin();
  let input: { recipe: Recipe; options?: { headless?: boolean; timeout?: number } };
  try {
    input = JSON.parse(raw);
  } catch {
    emit({ type: 'run_error', error: 'Invalid JSON on stdin' });
    process.exitCode = 1;
    return;
  }

  const recipe = input.recipe;
  const headless = input.options?.headless ?? true;
  const timeoutMs = input.options?.timeout ?? 120_000;

  const runId = `run-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const steps = recipe.workflow.steps;

  emit({ type: 'run_start', runId, totalSteps: steps.length });

  // 2. Launch browser
  let browser;
  try {
    browser = await chromium.launch({
      headless,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
  } catch (err) {
    emit({ type: 'run_error', error: `Browser launch failed: ${err instanceof Error ? err.message : String(err)}` });
    process.exitCode = 1;
    return;
  }

  // Enforce global timeout
  const timer = setTimeout(async () => {
    emit({ type: 'run_error', error: `Run timed out after ${timeoutMs}ms` });
    await browser.close().catch(() => {});
    process.exit(1);
  }, timeoutMs);

  let page;
  try {
    page = await browser.newPage();
    const tmpDir = await mkdtemp(join(tmpdir(), 'run-recipe-'));

    const engine = new PlaywrightFallbackEngine(page as any);
    const checkpoint = new AutoApproveCheckpointHandler();
    const budgetGuard = new BudgetGuard({
      budget: DEFAULT_BUDGET,
      downgradeOrder: ['trim_dom', 'drop_history', 'observe_scope_narrow', 'require_human_checkpoint'],
    });
    const healingMemory = new HealingMemory(join(tmpDir, 'healing.json'));
    const observeRefresher = new ObserveRefresher(engine);

    const stepExecutor = new StepExecutor(
      engine, engine, healingMemory, null, budgetGuard, checkpoint,
    );

    const recoveryPipeline = new RecoveryPipeline(
      observeRefresher, healingMemory, null, budgetGuard, checkpoint, engine, engine,
    );
    stepExecutor.setRecoveryPipeline(recoveryPipeline);

    // 3. Build RunContext
    const context: RunContext = {
      recipe,
      vars: {},
      budget: DEFAULT_BUDGET,
      usage: { llmCalls: 0, authoringCalls: 0, promptChars: 0, screenshots: 0 },
      runId,
      startedAt: new Date().toISOString(),
    };

    // 4. Execute steps one by one (replicating WorkflowRunner.run logic)
    const runStart = Date.now();
    const vars: Record<string, unknown> = {};

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      emit({ type: 'step_start', stepId: step.id, stepIndex: i, op: step.op });

      const stepStart = Date.now();
      const result = await stepExecutor.execute(step, context);
      const durationMs = Date.now() - stepStart;

      // Collect extracted data
      if (result.data) {
        Object.assign(vars, result.data);
      }

      emit({
        type: 'step_end',
        stepId: step.id,
        stepIndex: i,
        ok: result.ok,
        durationMs,
        ...(result.message ? { message: result.message } : {}),
        ...(result.errorType ? { errorType: result.errorType } : {}),
      });

      if (!result.ok) {
        const onFail = step.onFail ?? 'fallback';
        if (onFail === 'abort' || onFail === 'fallback' || onFail === 'retry') {
          emit({
            type: 'run_complete',
            ok: false,
            totalDurationMs: Date.now() - runStart,
            vars,
            abortedAt: step.id,
          });
          return;
        }
        // 'checkpoint' with auto-approve continues
      }
    }

    emit({
      type: 'run_complete',
      ok: true,
      totalDurationMs: Date.now() - runStart,
      vars,
    });
  } catch (err) {
    emit({
      type: 'run_error',
      error: err instanceof Error ? err.message : String(err),
    });
    process.exitCode = 1;
  } finally {
    clearTimeout(timer);
    if (page) await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main();
