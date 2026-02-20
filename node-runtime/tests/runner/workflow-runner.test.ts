import { describe, it, expect, vi, beforeEach } from 'vitest';
import { WorkflowRunner } from '../../src/runner/workflow-runner.js';
import { StepExecutor } from '../../src/runner/step-executor.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';
import type { CheckpointHandler } from '../../src/runner/checkpoint.js';
import type { RunContext, StepResult, Recipe } from '../../src/types/index.js';

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

function mockCheckpoint(decision: 'GO' | 'NOT_GO' = 'GO'): CheckpointHandler {
  return {
    requestApproval: vi.fn().mockResolvedValue(decision),
  };
}

function makeRecipe(): Recipe {
  return {
    domain: 'example.com',
    flow: 'test',
    version: 'v001',
    workflow: {
      id: 'test_flow',
      steps: [
        { id: 'open', op: 'goto', args: { url: 'https://example.com' } },
        { id: 'login', op: 'act_cached', targetKey: 'login.submit' },
      ],
    },
    actions: {
      'login.submit': {
        instruction: 'click login',
        preferred: { selector: '#login', description: 'Login', method: 'click' },
        observedAt: '2026-02-20T00:00:00Z',
      },
    },
    selectors: {},
    policies: {},
    fingerprints: {},
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

describe('WorkflowRunner', () => {
  let stagehand: BrowserEngine;
  let playwright: BrowserEngine;
  let checkpoint: CheckpointHandler;

  beforeEach(() => {
    stagehand = mockEngine();
    playwright = mockEngine();
    checkpoint = mockCheckpoint('GO');
  });

  it('runs a complete workflow successfully', async () => {
    const mockExecutor = {
      execute: vi.fn().mockResolvedValue({ stepId: 'open', ok: true }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(makeContext());

    expect(result.ok).toBe(true);
    expect(result.stepResults).toHaveLength(2);
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
  });

  it('aborts when GO/NOT GO returns NOT_GO', async () => {
    checkpoint = mockCheckpoint('NOT_GO');
    const mockExecutor = { execute: vi.fn() } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(makeContext());

    expect(result.ok).toBe(false);
    expect(result.abortedAt).toBe('go_not_go');
    expect(mockExecutor.execute).not.toHaveBeenCalled();
  });

  it('aborts on step failure with onFail=abort', async () => {
    const context = makeContext();
    context.recipe.workflow.steps = [
      { id: 'critical', op: 'act_cached', targetKey: 'login.submit', onFail: 'abort' },
    ];

    const mockExecutor = {
      execute: vi.fn().mockResolvedValue({
        stepId: 'critical',
        ok: false,
        errorType: 'TargetNotFound',
        message: 'Not found',
      }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(context);

    expect(result.ok).toBe(false);
    expect(result.abortedAt).toBe('critical');
  });

  it('continues on step failure when checkpoint approves', async () => {
    const context = makeContext();
    context.recipe.workflow.steps = [
      { id: 'step1', op: 'act_cached', targetKey: 'login.submit', onFail: 'checkpoint' },
      { id: 'step2', op: 'goto', args: { url: 'https://example.com/next' } },
    ];

    let callCount = 0;
    const mockExecutor = {
      execute: vi.fn().mockImplementation(async () => {
        callCount++;
        if (callCount === 1) {
          return { stepId: 'step1', ok: false, errorType: 'TargetNotFound' };
        }
        return { stepId: 'step2', ok: true };
      }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(context);

    expect(result.ok).toBe(true);
    expect(result.stepResults).toHaveLength(2);
  });

  it('stops when checkpoint rejects on step failure', async () => {
    const context = makeContext();
    context.recipe.workflow.steps = [
      { id: 'step1', op: 'act_cached', targetKey: 'login.submit', onFail: 'checkpoint' },
      { id: 'step2', op: 'goto', args: { url: 'https://example.com/next' } },
    ];

    // First call is GO (initial), second call is NOT_GO (on failure)
    let approvalCount = 0;
    checkpoint = {
      requestApproval: vi.fn().mockImplementation(async () => {
        approvalCount++;
        return approvalCount === 1 ? 'GO' : 'NOT_GO';
      }),
    };

    const mockExecutor = {
      execute: vi.fn().mockResolvedValue({
        stepId: 'step1',
        ok: false,
        errorType: 'TargetNotFound',
      }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(context);

    expect(result.ok).toBe(false);
    expect(result.abortedAt).toBe('step1');
  });

  it('passes fingerprint preflight when no fingerprints', async () => {
    const context = makeContext();
    context.recipe.fingerprints = {};

    const mockExecutor = {
      execute: vi.fn().mockResolvedValue({ stepId: 'open', ok: true }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(context);

    expect(result.ok).toBe(true);
  });

  it('reports durationMs', async () => {
    const mockExecutor = {
      execute: vi.fn().mockResolvedValue({ stepId: 'open', ok: true }),
    } as unknown as StepExecutor;

    const runner = new WorkflowRunner(stagehand, playwright, mockExecutor, checkpoint);
    const result = await runner.run(makeContext());

    expect(typeof result.durationMs).toBe('number');
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
  });
});
