import { readFile, writeFile, readdir, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import type { RunMetrics } from './collector.js';

export interface MetricsFilter {
  flow?: string;
  since?: string;
  until?: string;
}

export class MetricsStore {
  private initialized = false;

  constructor(private storeDir: string) {}

  private async ensureDir(): Promise<void> {
    if (this.initialized) return;
    await mkdir(this.storeDir, { recursive: true });
    this.initialized = true;
  }

  async save(metrics: RunMetrics): Promise<void> {
    await this.ensureDir();
    const filename = `${metrics.runId}.json`;
    const filepath = join(this.storeDir, filename);
    await writeFile(filepath, JSON.stringify(metrics, null, 2), 'utf-8');
  }

  async load(runId: string): Promise<RunMetrics | null> {
    try {
      const filepath = join(this.storeDir, `${runId}.json`);
      const content = await readFile(filepath, 'utf-8');
      return JSON.parse(content) as RunMetrics;
    } catch {
      return null;
    }
  }

  async loadAll(filter?: MetricsFilter): Promise<RunMetrics[]> {
    await this.ensureDir();
    const files = await this.listMetricsFiles();
    const metrics: RunMetrics[] = [];

    for (const file of files) {
      const content = await readFile(join(this.storeDir, file), 'utf-8');
      const m = JSON.parse(content) as RunMetrics;
      if (this.matchesFilter(m, filter)) {
        metrics.push(m);
      }
    }

    // Sort by startedAt ascending
    metrics.sort((a, b) => new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime());
    return metrics;
  }

  async loadRecent(count: number): Promise<RunMetrics[]> {
    if (count <= 0) return [];
    const all = await this.loadAll();
    // Already sorted ascending, return last N
    return all.slice(-count);
  }

  private async listMetricsFiles(): Promise<string[]> {
    try {
      const entries = await readdir(this.storeDir);
      return entries.filter((f) => f.endsWith('.json'));
    } catch {
      return [];
    }
  }

  private matchesFilter(metrics: RunMetrics, filter?: MetricsFilter): boolean {
    if (!filter) return true;

    if (filter.flow && metrics.flow !== filter.flow) return false;

    const startedAt = new Date(metrics.startedAt).getTime();

    if (filter.since && startedAt < new Date(filter.since).getTime()) return false;
    if (filter.until && startedAt > new Date(filter.until).getTime()) return false;

    return true;
  }
}
