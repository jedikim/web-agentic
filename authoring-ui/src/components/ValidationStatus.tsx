import { useValidation } from '../hooks/useValidation.ts';
import { useRecipeStore } from '../store/recipeStore.ts';

export function ValidationStatus() {
  const { isValid, errorCount, errors } = useValidation();
  const stepCount = useRecipeStore((s) => s.workflow.steps.length);
  const actionCount = useRecipeStore((s) => Object.keys(s.actions).length);
  const selectorCount = useRecipeStore((s) => Object.keys(s.selectors).length);

  return (
    <div className={`validation-status ${isValid ? 'valid' : 'invalid'}`}>
      <span className="validation-indicator">
        {isValid ? 'Valid' : `${errorCount} error${errorCount !== 1 ? 's' : ''}`}
      </span>
      <span className="validation-stat">Steps: {stepCount}</span>
      <span className="validation-stat">Actions: {actionCount}</span>
      <span className="validation-stat">Selectors: {selectorCount}</span>
      {!isValid && (
        <span className="validation-errors-preview" title={errors.map((e) => e.message).join('\n')}>
          {errors[0]?.message}
        </span>
      )}
    </div>
  );
}
