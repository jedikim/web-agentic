import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { join, basename } from 'node:path';
import type { StepResult } from '../types/step-result.js';

export interface TraceArtifact {
  filename: string;
  content: Buffer;
}

/** Legacy bundle format for backward compatibility */
export interface TraceBundle {
  runDir: string;
  screenshots: TraceArtifact[];
  domSnippets: TraceArtifact[];
  logs: string | null;
  summary: string | null;
}

export interface TraceStep {
  stepId: string;
  op: string;
  targetKey?: string;
  result: StepResult;
  screenshotPath?: string;
  domSnippetPath?: string;
  recoveryMethod?: string;
  durationMs: number;
}

export interface TraceMetadata {
  totalSteps: number;
  passedSteps: number;
  failedSteps: number;
  recoveredSteps: number;
  llmCalls: number;
  patchesApplied: number;
}

export interface StructuredTraceBundle {
  runId: string;
  flow: string;
  version: string;
  timestamp: string;
  steps: TraceStep[];
  metadata: TraceMetadata;
}

/**
 * Package trace artifacts (screenshots, DOM snippets, logs) from a run directory.
 * Legacy function preserved for backward compatibility.
 */
export async function bundleTrace(runDir: string): Promise<TraceBundle> {
  const files = await readdir(runDir);

  const screenshots: TraceArtifact[] = [];
  const domSnippets: TraceArtifact[] = [];
  let logs: string | null = null;
  let summary: string | null = null;

  for (const file of files) {
    const filePath = join(runDir, file);

    if (file.startsWith('step_') && file.endsWith('.png')) {
      const content = await readFile(filePath);
      screenshots.push({ filename: file, content });
    } else if (file.startsWith('dom_') && file.endsWith('.html')) {
      const content = await readFile(filePath);
      domSnippets.push({ filename: file, content });
    } else if (file === 'logs.jsonl') {
      logs = await readFile(filePath, 'utf-8');
    } else if (file === 'summary.md') {
      summary = await readFile(filePath, 'utf-8');
    }
  }

  return {
    runDir,
    screenshots,
    domSnippets,
    logs,
    summary,
  };
}

/**
 * Enhanced TraceBundler that creates structured trace bundles with full step data.
 * Supports creating, saving, and loading bundles for trace-based regression testing.
 */
export class TraceBundler {
  /**
   * Create a structured trace bundle from a run directory.
   * Reads logs.jsonl for step data, collects screenshots and DOM snippets.
   */
  async createBundle(runDir: string): Promise<StructuredTraceBundle> {
    const files = await readdir(runDir);
    const steps: TraceStep[] = [];
    let flow = '';
    let version = '';
    let runId = basename(runDir);
    let timestamp = new Date().toISOString();
    let llmCalls = 0;
    let patchesApplied = 0;

    // Parse logs.jsonl for step results
    if (files.includes('logs.jsonl')) {
      const logsContent = await readFile(join(runDir, 'logs.jsonl'), 'utf-8');
      const lines = logsContent.trim().split('\n').filter(Boolean);

      for (const line of lines) {
        const entry = JSON.parse(line) as Record<string, unknown>;
        const stepId = (entry.stepId as string) ?? '';
        const ok = entry.ok as boolean;

        const step: TraceStep = {
          stepId,
          op: (entry.op as string) ?? '',
          targetKey: entry.targetKey as string | undefined,
          result: {
            stepId,
            ok,
            data: entry.data as Record<string, unknown> | undefined,
            errorType: entry.errorType as StepResult['errorType'],
            message: entry.message as string | undefined,
            durationMs: entry.durationMs as number | undefined,
          },
          durationMs: (entry.durationMs as number) ?? 0,
        };

        // Check for screenshot and DOM snippet files
        const screenshotFile = `step_${stepId}.png`;
        if (files.includes(screenshotFile)) {
          step.screenshotPath = screenshotFile;
        }
        const domFile = `dom_${stepId}.html`;
        if (files.includes(domFile)) {
          step.domSnippetPath = domFile;
        }

        if (entry.recoveryMethod) {
          step.recoveryMethod = entry.recoveryMethod as string;
        }

        steps.push(step);
      }

      // Extract metadata from first log entry if available
      if (lines.length > 0) {
        const first = JSON.parse(lines[0]) as Record<string, unknown>;
        timestamp = (first.timestamp as string) ?? timestamp;
      }
    }

    // Try to read trace-meta.json if it exists
    if (files.includes('trace-meta.json')) {
      const metaContent = await readFile(join(runDir, 'trace-meta.json'), 'utf-8');
      const meta = JSON.parse(metaContent) as Record<string, unknown>;
      flow = (meta.flow as string) ?? flow;
      version = (meta.version as string) ?? version;
      runId = (meta.runId as string) ?? runId;
      llmCalls = (meta.llmCalls as number) ?? llmCalls;
      patchesApplied = (meta.patchesApplied as number) ?? patchesApplied;
    }

    const passedSteps = steps.filter((s) => s.result.ok).length;
    const failedSteps = steps.filter((s) => !s.result.ok).length;
    const recoveredSteps = steps.filter((s) => s.recoveryMethod).length;

    return {
      runId,
      flow,
      version,
      timestamp,
      steps,
      metadata: {
        totalSteps: steps.length,
        passedSteps,
        failedSteps,
        recoveredSteps,
        llmCalls,
        patchesApplied,
      },
    };
  }

  /**
   * Save a structured trace bundle as trace.json in the output directory.
   * Returns the path to the saved bundle file.
   */
  async saveBundle(bundle: StructuredTraceBundle, outputPath: string): Promise<string> {
    await mkdir(outputPath, { recursive: true });
    const tracePath = join(outputPath, 'trace.json');
    await writeFile(tracePath, JSON.stringify(bundle, null, 2), 'utf-8');
    return tracePath;
  }

  /**
   * Load a previously saved structured trace bundle from a file path.
   */
  async loadBundle(bundlePath: string): Promise<StructuredTraceBundle> {
    const content = await readFile(bundlePath, 'utf-8');
    return JSON.parse(content) as StructuredTraceBundle;
  }
}
