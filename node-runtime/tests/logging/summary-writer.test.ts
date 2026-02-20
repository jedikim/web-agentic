import { describe, it, expect } from 'vitest';
import { buildSummaryMarkdown } from '../../src/logging/summary-writer.js';
import type { RunContext } from '../../src/types/recipe.js';
import type { StepResult } from '../../src/types/step-result.js';

function makeContext(overrides?: Partial<RunContext>): RunContext {
  return {
    recipe: {
      domain: 'example.com',
      flow: 'booking_flow',
      version: 'v001',
      workflow: { id: 'booking_flow', steps: [] },
      actions: {},
      selectors: {},
      policies: {},
      fingerprints: {},
    },
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
    usage: { llmCalls: 1, authoringCalls: 0, promptChars: 2000, screenshots: 1 },
    runId: 'run-123',
    startedAt: '2026-02-21T10:00:00Z',
    ...overrides,
  };
}

describe('buildSummaryMarkdown', () => {
  it('generates a successful run summary', () => {
    const results: StepResult[] = [
      { stepId: 'open', ok: true, durationMs: 1000 },
      { stepId: 'login', ok: true, durationMs: 2000 },
      { stepId: 'extract', ok: true, durationMs: 3000 },
    ];

    const md = buildSummaryMarkdown(makeContext(), results, false);

    expect(md).toContain('# Run Summary');
    expect(md).toContain('Result: Success');
    expect(md).toContain('Duration: 00m 06s');
    expect(md).toContain('LLM Calls: 1');
    expect(md).toContain('Steps: 3/3 passed');
    expect(md).toContain('All steps completed successfully');
    expect(md).toContain('No patches applied');
  });

  it('generates a partial failure summary with events', () => {
    const results: StepResult[] = [
      { stepId: 'open', ok: true, durationMs: 1000 },
      { stepId: 'login', ok: false, errorType: 'TargetNotFound', message: 'button missing', durationMs: 5000 },
    ];

    const md = buildSummaryMarkdown(makeContext(), results, true, 'v002');

    expect(md).toContain('Result: Partial Failure');
    expect(md).toContain('Steps: 1/2 passed');
    expect(md).toContain('Step "login": TargetNotFound');
    expect(md).toContain('Output recipe: v002');
  });

  it('includes operator notes when provided', () => {
    const results: StepResult[] = [
      { stepId: 'step1', ok: true, durationMs: 1000 },
    ];

    const md = buildSummaryMarkdown(
      makeContext(),
      results,
      false,
      undefined,
      ['Next run should be faster', 'Check selector for login'],
    );

    expect(md).toContain('## Operator Notes');
    expect(md).toContain('Next run should be faster');
    expect(md).toContain('Check selector for login');
  });

  it('includes run info section', () => {
    const md = buildSummaryMarkdown(makeContext(), [], false);

    expect(md).toContain('Run ID: run-123');
    expect(md).toContain('Started at: 2026-02-21T10:00:00Z');
    expect(md).toContain('Authoring calls: 0');
    expect(md).toContain('Prompt chars used: 2000');
  });

  it('formats duration correctly', () => {
    const results: StepResult[] = [
      { stepId: 'step1', ok: true, durationMs: 192000 },
    ];

    const md = buildSummaryMarkdown(makeContext(), results, false);
    expect(md).toContain('Duration: 03m 12s');
  });
});
