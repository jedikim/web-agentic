import type { Recipe, PatchPayload } from '../types/index.js';
import { applyPatch } from '../recipe/patch-merger.js';
import { saveRecipeVersion } from '../recipe/versioning.js';
import type { CheckpointHandler } from './checkpoint.js';

export type PatchSeverity = 'minor' | 'major';

/**
 * PatchWorkflow handles patch classification, application, and recipe version-up.
 * Minor patches (single selector/action replace) are auto-applied.
 * Major patches (multiple changes, policy/workflow updates) require GO/NOT GO approval.
 */
export class PatchWorkflow {
  constructor(
    private checkpointHandler: CheckpointHandler,
  ) {}

  /**
   * Classify patch severity:
   * - minor: single selector/action replacement
   * - major: multiple changes, policy update, workflow change
   */
  classifyPatch(payload: PatchPayload): PatchSeverity {
    // Single op that's a replace → minor
    if (payload.patch.length === 1) {
      const op = payload.patch[0].op;
      if (op === 'actions.replace' || op === 'selectors.replace') {
        return 'minor';
      }
    }

    // Multiple ops → major
    if (payload.patch.length > 1) {
      return 'major';
    }

    // Policy or workflow changes → major
    const op = payload.patch[0]?.op;
    if (op === 'policies.update' || op === 'workflow.update_expect') {
      return 'major';
    }

    // New additions are minor (single add)
    if (op === 'actions.add' || op === 'selectors.add') {
      return 'minor';
    }

    return 'minor';
  }

  /**
   * Apply patch to recipe, version up, save new version.
   * Major patches require checkpoint approval.
   */
  async applyAndVersionUp(
    recipe: Recipe,
    payload: PatchPayload,
    basePath: string,
  ): Promise<Recipe> {
    const severity = this.classifyPatch(payload);

    if (severity === 'major') {
      const approval = await this.checkpointHandler.requestApproval(
        `Major patch: ${payload.reason}. Apply?`,
      );
      if (approval === 'NOT_GO') {
        throw new Error('Patch rejected by user');
      }
    }

    const patched = applyPatch(recipe, payload);
    const newVersion = await saveRecipeVersion(basePath, patched);
    return { ...patched, version: newVersion };
  }
}
