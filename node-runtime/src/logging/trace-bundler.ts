import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

export interface TraceArtifact {
  filename: string;
  content: Buffer;
}

export interface TraceBundle {
  runDir: string;
  screenshots: TraceArtifact[];
  domSnippets: TraceArtifact[];
  logs: string | null;
  summary: string | null;
}

/**
 * Package trace artifacts (screenshots, DOM snippets, logs) from a run directory.
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
