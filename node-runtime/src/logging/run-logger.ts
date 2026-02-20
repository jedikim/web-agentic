import { writeFile, appendFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import type { StepResult } from '../types/step-result.js';

export class RunLogger {
  private logPath: string;
  private initialized = false;

  constructor(private runDir: string) {
    this.logPath = join(runDir, 'logs.jsonl');
  }

  private async ensureDir(): Promise<void> {
    if (this.initialized) return;
    await mkdir(this.runDir, { recursive: true });
    this.initialized = true;
  }

  async logStep(result: StepResult): Promise<void> {
    await this.ensureDir();
    const entry = {
      timestamp: new Date().toISOString(),
      ...result,
    };
    await appendFile(this.logPath, JSON.stringify(entry) + '\n', 'utf-8');
  }

  async saveScreenshot(stepId: string, buffer: Buffer): Promise<void> {
    await this.ensureDir();
    const filePath = join(this.runDir, `step_${stepId}.png`);
    await writeFile(filePath, buffer);
  }

  async saveDomSnippet(stepId: string, html: string): Promise<void> {
    await this.ensureDir();
    const filePath = join(this.runDir, `dom_${stepId}.html`);
    await writeFile(filePath, html, 'utf-8');
  }

  getRunDir(): string {
    return this.runDir;
  }
}
