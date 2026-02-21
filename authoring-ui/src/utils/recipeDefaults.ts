import type { Workflow, ActionsMap, SelectorsMap, FingerprintsMap, PoliciesMap } from '../validation/schemas.ts';

export const defaultWorkflow: Workflow = {
  id: 'new-workflow',
  version: 'v001',
  vars: {},
  steps: [
    {
      id: 'step-1',
      op: 'goto',
      args: { url: 'https://example.com' },
    },
  ],
};

export const defaultActions: ActionsMap = {};

export const defaultSelectors: SelectorsMap = {};

export const defaultFingerprints: FingerprintsMap = {};

export const defaultPolicies: PoliciesMap = {};

export interface RecipeData {
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  fingerprints: FingerprintsMap;
  policies: PoliciesMap;
}

export function createDefaultRecipe(): RecipeData {
  return {
    workflow: structuredClone(defaultWorkflow),
    actions: structuredClone(defaultActions),
    selectors: structuredClone(defaultSelectors),
    fingerprints: structuredClone(defaultFingerprints),
    policies: structuredClone(defaultPolicies),
  };
}
