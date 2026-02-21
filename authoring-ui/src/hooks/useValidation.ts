import { useMemo } from 'react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { useUiStore } from '../store/uiStore.ts';
import type { ValidationError, RecipeFileTab } from '../store/uiStore.ts';
import {
  WorkflowSchema,
  ActionsMapSchema,
  SelectorsMapSchema,
  FingerprintsMapSchema,
  PoliciesMapSchema,
} from '../validation/schemas.ts';
import type { ZodError } from 'zod';

function zodErrorToValidationErrors(error: ZodError, file: RecipeFileTab): ValidationError[] {
  return error.issues.map((issue) => ({
    file,
    path: issue.path.join('.'),
    message: issue.message,
  }));
}

export function validateRecipe(state: {
  workflow: unknown;
  actions: unknown;
  selectors: unknown;
  fingerprints: unknown;
  policies: unknown;
}): ValidationError[] {
  const errors: ValidationError[] = [];

  const wfResult = WorkflowSchema.safeParse(state.workflow);
  if (!wfResult.success) {
    errors.push(...zodErrorToValidationErrors(wfResult.error, 'workflow'));
  }

  const actResult = ActionsMapSchema.safeParse(state.actions);
  if (!actResult.success) {
    errors.push(...zodErrorToValidationErrors(actResult.error, 'actions'));
  }

  const selResult = SelectorsMapSchema.safeParse(state.selectors);
  if (!selResult.success) {
    errors.push(...zodErrorToValidationErrors(selResult.error, 'selectors'));
  }

  const fpResult = FingerprintsMapSchema.safeParse(state.fingerprints);
  if (!fpResult.success) {
    errors.push(...zodErrorToValidationErrors(fpResult.error, 'fingerprints'));
  }

  const polResult = PoliciesMapSchema.safeParse(state.policies);
  if (!polResult.success) {
    errors.push(...zodErrorToValidationErrors(polResult.error, 'policies'));
  }

  // Cross-reference: act_cached targetKeys must exist in actions
  if (wfResult.success && actResult.success) {
    const actionKeys = new Set(Object.keys(state.actions as Record<string, unknown>));
    for (const step of wfResult.data.steps) {
      if (step.op === 'act_cached' && step.targetKey && !actionKeys.has(step.targetKey)) {
        errors.push({
          file: 'workflow',
          path: `steps.${step.id}.targetKey`,
          message: `targetKey "${step.targetKey}" not found in actions`,
        });
      }
    }
  }

  return errors;
}

export function useValidation() {
  const workflow = useRecipeStore((s) => s.workflow);
  const actions = useRecipeStore((s) => s.actions);
  const selectors = useRecipeStore((s) => s.selectors);
  const fingerprints = useRecipeStore((s) => s.fingerprints);
  const policies = useRecipeStore((s) => s.policies);
  const setValidationErrors = useUiStore((s) => s.setValidationErrors);

  const errors = useMemo(() => {
    const errs = validateRecipe({ workflow, actions, selectors, fingerprints, policies });
    setValidationErrors(errs);
    return errs;
  }, [workflow, actions, selectors, fingerprints, policies, setValidationErrors]);

  return {
    errors,
    isValid: errors.length === 0,
    errorCount: errors.length,
    errorsByFile: (file: RecipeFileTab) => errors.filter((e) => e.file === file),
  };
}
