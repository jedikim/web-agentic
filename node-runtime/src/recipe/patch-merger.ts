import type {
  Recipe,
  PatchPayload,
  PatchOp,
  ActionEntry,
  SelectorEntry,
  Expectation,
  Policy,
} from '../types/index.js';

function applyOp(recipe: Recipe, op: PatchOp): Recipe {
  switch (op.op) {
    case 'actions.replace': {
      if (!op.key) throw new Error('actions.replace requires a key');
      return {
        ...recipe,
        actions: {
          ...recipe.actions,
          [op.key]: op.value as ActionEntry,
        },
      };
    }

    case 'actions.add': {
      if (!op.key) throw new Error('actions.add requires a key');
      if (recipe.actions[op.key]) {
        throw new Error(`actions.add: key "${op.key}" already exists`);
      }
      return {
        ...recipe,
        actions: {
          ...recipe.actions,
          [op.key]: op.value as ActionEntry,
        },
      };
    }

    case 'selectors.add': {
      if (!op.key) throw new Error('selectors.add requires a key');
      if (recipe.selectors[op.key]) {
        throw new Error(`selectors.add: key "${op.key}" already exists`);
      }
      return {
        ...recipe,
        selectors: {
          ...recipe.selectors,
          [op.key]: op.value as SelectorEntry,
        },
      };
    }

    case 'selectors.replace': {
      if (!op.key) throw new Error('selectors.replace requires a key');
      return {
        ...recipe,
        selectors: {
          ...recipe.selectors,
          [op.key]: op.value as SelectorEntry,
        },
      };
    }

    case 'workflow.update_expect': {
      if (!op.step) throw new Error('workflow.update_expect requires a step');
      return {
        ...recipe,
        workflow: {
          ...recipe.workflow,
          steps: recipe.workflow.steps.map((s) =>
            s.id === op.step ? { ...s, expect: op.value as Expectation[] } : s,
          ),
        },
      };
    }

    case 'policies.update': {
      if (!op.key) throw new Error('policies.update requires a key');
      return {
        ...recipe,
        policies: {
          ...recipe.policies,
          [op.key]: op.value as Policy,
        },
      };
    }

    default:
      throw new Error(`Unknown patch op: ${op.op}`);
  }
}

export function applyPatch(recipe: Recipe, payload: PatchPayload): Recipe {
  let result = recipe;
  for (const op of payload.patch) {
    result = applyOp(result, op);
  }
  return result;
}
