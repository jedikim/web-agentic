import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { StepResult } from '../types/step-result.js';
import type { RunContext } from '../types/recipe.js';

export interface SummaryOptions {
  runDir: string;
  context: RunContext;
  results: StepResult[];
  patchApplied: boolean;
  outputVersion?: string;
  operatorNotes?: string[];
}

/**
 * Generate a human-readable markdown summary following Blueprint section 9.
 */
export async function writeSummary(options: SummaryOptions): Promise<void> {
  const { runDir, context, results, patchApplied, outputVersion, operatorNotes } = options;
  const md = buildSummaryMarkdown(context, results, patchApplied, outputVersion, operatorNotes);
  await writeFile(join(runDir, 'summary.md'), md, 'utf-8');
}

export function buildSummaryMarkdown(
  context: RunContext,
  results: StepResult[],
  patchApplied: boolean,
  outputVersion?: string,
  operatorNotes?: string[],
): string {
  const totalSteps = results.length;
  const successSteps = results.filter((r) => r.ok).length;
  const failedSteps = results.filter((r) => !r.ok);
  const overallResult = failedSteps.length === 0 ? 'Success' : 'Partial Failure';

  const totalDurationMs = results.reduce((sum, r) => sum + (r.durationMs ?? 0), 0);
  const durationStr = formatDuration(totalDurationMs);

  const lines: string[] = [
    '# Run Summary',
    `- Goal: ${context.recipe.flow} (${context.recipe.domain})`,
    `- Result: ${overallResult}`,
    `- Duration: ${durationStr}`,
    `- LLM Calls: ${context.usage.llmCalls}`,
    `- Steps: ${successSteps}/${totalSteps} passed`,
    '',
    '## Key Events',
  ];

  let eventNum = 1;
  for (const result of results) {
    if (!result.ok) {
      lines.push(`${eventNum}. Step "${result.stepId}": ${result.errorType ?? 'unknown error'} - ${result.message ?? 'no details'}`);
      eventNum++;
    }
  }

  if (eventNum === 1) {
    lines.push('- All steps completed successfully');
  }

  lines.push('');
  lines.push('## Version');
  lines.push(`- Input recipe: ${context.recipe.version}`);
  if (patchApplied && outputVersion) {
    lines.push(`- Output recipe: ${outputVersion}`);
  } else {
    lines.push('- No patches applied');
  }

  lines.push('');
  lines.push('## Run Info');
  lines.push(`- Run ID: ${context.runId}`);
  lines.push(`- Started at: ${context.startedAt}`);
  lines.push(`- Authoring calls: ${context.usage.authoringCalls}`);
  lines.push(`- Prompt chars used: ${context.usage.promptChars}`);

  if (operatorNotes && operatorNotes.length > 0) {
    lines.push('');
    lines.push('## Operator Notes');
    for (const note of operatorNotes) {
      lines.push(`- ${note}`);
    }
  }

  return lines.join('\n') + '\n';
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}m ${String(seconds).padStart(2, '0')}s`;
}
