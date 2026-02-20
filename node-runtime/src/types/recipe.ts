import type { Workflow } from './workflow.js';
import type { ActionsMap } from './action.js';
import type { SelectorsMap } from './selector.js';
import type { PoliciesMap } from './policy.js';
import type { FingerprintsMap } from './fingerprint.js';
import type { TokenBudget, BudgetUsage } from './budget.js';

export interface Recipe {
  domain: string;
  flow: string;
  version: string;
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  policies: PoliciesMap;
  fingerprints: FingerprintsMap;
}

export interface RunContext {
  recipe: Recipe;
  vars: Record<string, unknown>;
  budget: TokenBudget;
  usage: BudgetUsage;
  runId: string;
  startedAt: string;
}
