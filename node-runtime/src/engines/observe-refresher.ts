import type { ActionRef } from '../types/index.js';
import type { BrowserEngine } from './browser-engine.js';

/**
 * ObserveRefresher wraps BrowserEngine.observe() to re-discover actions
 * for a given target key. Scopes the observation to minimize token usage.
 * Updates the actions cache on success.
 */
export class ObserveRefresher {
  constructor(private engine: BrowserEngine) {}

  /**
   * Use observe() to re-discover an action for a target key.
   * @param targetKey - The action target key to refresh
   * @param instruction - Natural language instruction for observe()
   * @param scope - Optional CSS selector to scope observation
   * @returns The first matching ActionRef, or null if none found
   */
  async refresh(
    targetKey: string,
    instruction: string,
    scope?: string,
  ): Promise<ActionRef | null> {
    const actions = await this.engine.observe(instruction, scope);
    return actions.length > 0 ? actions[0] : null;
  }
}
