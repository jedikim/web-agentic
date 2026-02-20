import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { ActionRef } from '../types/action.js';

interface HealingEntry {
  targetKey: string;
  url: string;
  action: ActionRef;
  healedAt: string;
  successCount: number;
}

interface HealingStore {
  entries: HealingEntry[];
}

/**
 * HealingMemory stores previously successful ActionRefs for target keys.
 * Uses JSON file-based storage per Blueprint design.
 * Only allows "evidence-based healing" - uses past success as the basis.
 */
export class HealingMemory {
  private store: HealingStore | null = null;

  constructor(private filePath: string) {}

  private async load(): Promise<HealingStore> {
    if (this.store) return this.store;

    try {
      const data = await readFile(this.filePath, 'utf-8');
      this.store = JSON.parse(data) as HealingStore;
    } catch {
      this.store = { entries: [] };
    }
    return this.store;
  }

  private async save(): Promise<void> {
    if (!this.store) return;
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(this.store, null, 2), 'utf-8');
  }

  /**
   * Find a previously successful ActionRef for the given targetKey and URL.
   * Matches on targetKey first, then prefers entries from the same URL domain.
   */
  async findMatch(targetKey: string, currentUrl: string): Promise<ActionRef | null> {
    const store = await this.load();
    const currentDomain = extractDomain(currentUrl);

    // Filter entries matching the targetKey
    const matches = store.entries.filter((e) => e.targetKey === targetKey);
    if (matches.length === 0) return null;

    // Prefer matches from the same domain
    const sameDomain = matches.filter((e) => extractDomain(e.url) === currentDomain);
    if (sameDomain.length > 0) {
      // Return the one with the highest success count
      sameDomain.sort((a, b) => b.successCount - a.successCount);
      return sameDomain[0].action;
    }

    // Fall back to any match, sorted by success count
    matches.sort((a, b) => b.successCount - a.successCount);
    return matches[0].action;
  }

  /**
   * Record a successful action for a target key.
   * If an entry already exists for the same targetKey + URL, increment successCount.
   */
  async record(targetKey: string, action: ActionRef, url: string): Promise<void> {
    const store = await this.load();

    const existing = store.entries.find(
      (e) => e.targetKey === targetKey && e.url === url && e.action.selector === action.selector,
    );

    if (existing) {
      existing.successCount++;
      existing.healedAt = new Date().toISOString();
      existing.action = action;
    } else {
      store.entries.push({
        targetKey,
        url,
        action,
        healedAt: new Date().toISOString(),
        successCount: 1,
      });
    }

    await this.save();
  }

  /**
   * Get all entries (for testing/debugging).
   */
  async getAll(): Promise<HealingEntry[]> {
    const store = await this.load();
    return [...store.entries];
  }
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
