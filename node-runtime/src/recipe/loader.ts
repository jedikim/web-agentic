import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { Recipe } from '../types/index.js';
import {
  WorkflowSchema,
  ActionsMapSchema,
  SelectorsMapSchema,
  PoliciesMapSchema,
  FingerprintsMapSchema,
} from '../schemas/index.js';

export async function loadRecipe(basePath: string, version: string): Promise<Recipe> {
  const versionDir = join(basePath, version);

  const [workflowRaw, actionsRaw, selectorsRaw, policiesRaw, fingerprintsRaw] =
    await Promise.all([
      readFile(join(versionDir, 'workflow.json'), 'utf-8'),
      readFile(join(versionDir, 'actions.json'), 'utf-8'),
      readFile(join(versionDir, 'selectors.json'), 'utf-8'),
      readFile(join(versionDir, 'policies.json'), 'utf-8'),
      readFile(join(versionDir, 'fingerprints.json'), 'utf-8'),
    ]);

  const workflow = WorkflowSchema.parse(JSON.parse(workflowRaw));
  const actions = ActionsMapSchema.parse(JSON.parse(actionsRaw));
  const selectors = SelectorsMapSchema.parse(JSON.parse(selectorsRaw));
  const policies = PoliciesMapSchema.parse(JSON.parse(policiesRaw));
  const fingerprints = FingerprintsMapSchema.parse(JSON.parse(fingerprintsRaw));

  // Extract domain and flow from basePath (e.g., recipes/example.com/booking)
  const parts = basePath.split('/');
  const flow = parts[parts.length - 1] || 'default';
  const domain = parts[parts.length - 2] || 'unknown';

  return {
    domain,
    flow,
    version,
    workflow,
    actions,
    selectors,
    policies,
    fingerprints,
  };
}
