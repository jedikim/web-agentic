import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { ActionRef } from '../types/action.js';

export interface HealingEvidence {
  originalSelector: string;
  healedSelector: string;
  domContext: string;
  pageTitle: string;
  pageUrl: string;
  method: string;
  timestamp: string;
}

export interface HealingRecord {
  targetKey: string;
  action: ActionRef;
  url: string;
  domain: string;
  successCount: number;
  failCount: number;
  confidence: number;
  lastSuccessAt: string;
  lastFailAt?: string;
  createdAt: string;
  evidence: HealingEvidence;
}

export interface HealingStats {
  totalRecords: number;
  avgConfidence: number;
  hitRate: number;
  domainDistribution: Record<string, number>;
}

/** @deprecated Use HealingRecord instead */
interface LegacyHealingEntry {
  targetKey: string;
  url: string;
  action: ActionRef;
  healedAt: string;
  successCount: number;
}

interface HealingStore {
  entries: HealingRecord[];
}

/** @deprecated */
interface LegacyHealingStore {
  entries: LegacyHealingEntry[];
}

/**
 * HealingMemory stores previously successful ActionRefs for target keys.
 * Uses JSON file-based storage per Blueprint design.
 * Only allows "evidence-based healing" - uses past success as the basis.
 *
 * Enhanced with confidence scoring, failure tracking, and pruning.
 */
export class HealingMemory {
  private store: HealingStore | null = null;
  private lookupCount = 0;
  private hitCount = 0;

  constructor(private filePath: string) {}

  private async load(): Promise<HealingStore> {
    if (this.store) return this.store;

    try {
      const data = await readFile(this.filePath, 'utf-8');
      const parsed = JSON.parse(data) as HealingStore | LegacyHealingStore;
      this.store = this.migrateIfNeeded(parsed);
    } catch {
      this.store = { entries: [] };
    }
    return this.store;
  }

  /**
   * Migrate legacy entries (without evidence/confidence) to new format.
   */
  private migrateIfNeeded(parsed: HealingStore | LegacyHealingStore): HealingStore {
    if (parsed.entries.length === 0) return { entries: [] };

    const first = parsed.entries[0];
    // Detect legacy format: has 'healedAt' but no 'evidence'
    if ('healedAt' in first && !('evidence' in first)) {
      const legacyEntries = parsed.entries as LegacyHealingEntry[];
      const migrated: HealingRecord[] = legacyEntries.map((e) => ({
        targetKey: e.targetKey,
        action: e.action,
        url: e.url,
        domain: extractDomain(e.url),
        successCount: e.successCount,
        failCount: 0,
        confidence: 1.0,
        lastSuccessAt: e.healedAt,
        createdAt: e.healedAt,
        evidence: {
          originalSelector: '',
          healedSelector: e.action.selector,
          domContext: '',
          pageTitle: '',
          pageUrl: e.url,
          method: 'migration',
          timestamp: e.healedAt,
        },
      }));
      return { entries: migrated };
    }

    return parsed as HealingStore;
  }

  private async save(): Promise<void> {
    if (!this.store) return;
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(this.store, null, 2), 'utf-8');
  }

  /**
   * Find a previously successful ActionRef for the given targetKey and URL.
   * Only returns matches with confidence >= minConfidence (default 0.6).
   * Prefers same-domain matches, then cross-domain.
   */
  async findMatch(
    targetKey: string,
    currentUrl: string,
    minConfidence = 0.6,
  ): Promise<ActionRef | null> {
    const store = await this.load();
    const currentDomain = extractDomain(currentUrl);
    this.lookupCount++;

    // Filter entries matching the targetKey with sufficient confidence
    const matches = store.entries.filter(
      (e) => e.targetKey === targetKey && e.confidence >= minConfidence,
    );
    if (matches.length === 0) return null;

    this.hitCount++;

    // Prefer matches from the same domain
    const sameDomain = matches.filter((e) => e.domain === currentDomain);
    if (sameDomain.length > 0) {
      sameDomain.sort((a, b) => b.confidence - a.confidence || b.successCount - a.successCount);
      return sameDomain[0].action;
    }

    // Fall back to any match, sorted by confidence then success count
    matches.sort((a, b) => b.confidence - a.confidence || b.successCount - a.successCount);
    return matches[0].action;
  }

  /**
   * Record a successful healing with full evidence.
   * If an entry already exists for the same targetKey + URL + selector, increment successCount.
   */
  async record(
    targetKey: string,
    action: ActionRef,
    url: string,
    evidence: HealingEvidence,
  ): Promise<void> {
    const store = await this.load();
    const domain = extractDomain(url);
    const now = new Date().toISOString();

    const existing = store.entries.find(
      (e) => e.targetKey === targetKey && e.url === url && e.action.selector === action.selector,
    );

    if (existing) {
      existing.successCount++;
      existing.confidence = existing.successCount / (existing.successCount + existing.failCount);
      existing.lastSuccessAt = now;
      existing.action = action;
      existing.evidence = evidence;
    } else {
      store.entries.push({
        targetKey,
        action,
        url,
        domain,
        successCount: 1,
        failCount: 0,
        confidence: 1.0,
        lastSuccessAt: now,
        createdAt: now,
        evidence,
      });
    }

    await this.save();
  }

  /**
   * Record a failure for a targetKey at a URL.
   * Increments failCount and recalculates confidence for all matching entries.
   */
  async recordFailure(targetKey: string, url: string): Promise<void> {
    const store = await this.load();

    const matches = store.entries.filter((e) => e.targetKey === targetKey && e.url === url);
    const now = new Date().toISOString();

    for (const entry of matches) {
      entry.failCount++;
      entry.confidence = entry.successCount / (entry.successCount + entry.failCount);
      entry.lastFailAt = now;
    }

    if (matches.length > 0) {
      await this.save();
    }
  }

  /**
   * Remove records below confidence threshold or older than maxAgeDays.
   * Returns the number of pruned records.
   */
  async prune(options?: { minConfidence?: number; maxAgeDays?: number }): Promise<number> {
    const store = await this.load();
    const minConf = options?.minConfidence ?? 0.3;
    const maxAgeDays = options?.maxAgeDays;
    const now = Date.now();
    const originalCount = store.entries.length;

    store.entries = store.entries.filter((e) => {
      if (e.confidence < minConf) return false;
      if (maxAgeDays !== undefined) {
        const ageMs = now - new Date(e.lastSuccessAt).getTime();
        const ageDays = ageMs / (1000 * 60 * 60 * 24);
        if (ageDays > maxAgeDays) return false;
      }
      return true;
    });

    const pruned = originalCount - store.entries.length;
    if (pruned > 0) {
      await this.save();
    }
    return pruned;
  }

  /**
   * Get statistics about the healing memory store.
   */
  async getStats(): Promise<HealingStats> {
    const store = await this.load();
    const entries = store.entries;

    const totalRecords = entries.length;
    const avgConfidence =
      totalRecords > 0
        ? entries.reduce((sum, e) => sum + e.confidence, 0) / totalRecords
        : 0;

    const domainDistribution: Record<string, number> = {};
    for (const entry of entries) {
      domainDistribution[entry.domain] = (domainDistribution[entry.domain] ?? 0) + 1;
    }

    return {
      totalRecords,
      avgConfidence,
      hitRate: this.lookupCount > 0 ? this.hitCount / this.lookupCount : 0,
      domainDistribution,
    };
  }

  /**
   * Get all entries (for testing/debugging).
   */
  async getAll(): Promise<HealingRecord[]> {
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
