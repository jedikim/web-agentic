import { describe, it, expect } from 'vitest';
import { validateRecipe } from '../hooks/useValidation.ts';
import { createDefaultRecipe } from '../utils/recipeDefaults.ts';

describe('validateRecipe', () => {
  it('returns no errors for valid default recipe', () => {
    const recipe = createDefaultRecipe();
    const errors = validateRecipe(recipe);
    expect(errors).toHaveLength(0);
  });

  it('returns errors for invalid workflow (empty steps)', () => {
    const recipe = createDefaultRecipe();
    recipe.workflow.steps = [];
    const errors = validateRecipe(recipe);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => e.file === 'workflow')).toBe(true);
  });

  it('returns errors for invalid workflow step (missing id)', () => {
    const recipe = createDefaultRecipe();
    // @ts-expect-error testing invalid data
    recipe.workflow.steps = [{ op: 'goto' }];
    const errors = validateRecipe(recipe);
    expect(errors.some((e) => e.file === 'workflow')).toBe(true);
  });

  it('returns errors for invalid action entry', () => {
    const recipe = createDefaultRecipe();
    // @ts-expect-error testing invalid data
    recipe.actions = { bad: { notInstruction: true } };
    const errors = validateRecipe(recipe);
    expect(errors.some((e) => e.file === 'actions')).toBe(true);
  });

  it('returns errors for invalid selector entry', () => {
    const recipe = createDefaultRecipe();
    // @ts-expect-error testing invalid data
    recipe.selectors = { bad: { primary: 123 } };
    const errors = validateRecipe(recipe);
    expect(errors.some((e) => e.file === 'selectors')).toBe(true);
  });

  it('detects missing targetKey cross-reference', () => {
    const recipe = createDefaultRecipe();
    recipe.workflow.steps = [
      { id: 'step-1', op: 'act_cached', targetKey: 'nonexistent_key' },
    ];
    const errors = validateRecipe(recipe);
    expect(errors.some((e) => e.message.includes('nonexistent_key'))).toBe(true);
  });

  it('does not flag targetKey cross-ref if action exists', () => {
    const recipe = createDefaultRecipe();
    recipe.workflow.steps = [
      { id: 'step-1', op: 'act_cached', targetKey: 'click_link' },
    ];
    recipe.actions = {
      click_link: {
        instruction: 'Click the link',
        preferred: { selector: '#link', description: 'link', method: 'click' },
        observedAt: '2026-01-01',
      },
    };
    const errors = validateRecipe(recipe);
    expect(errors.some((e) => e.message.includes('click_link'))).toBe(false);
  });

  it('validates valid fingerprints', () => {
    const recipe = createDefaultRecipe();
    recipe.fingerprints = {
      homepage: {
        mustText: ['Welcome'],
        urlContains: 'example.com',
      },
    };
    const errors = validateRecipe(recipe);
    const fpErrors = errors.filter((e) => e.file === 'fingerprints');
    expect(fpErrors).toHaveLength(0);
  });

  it('validates valid policies', () => {
    const recipe = createDefaultRecipe();
    recipe.policies = {
      default: {
        hard: [{ field: 'price', op: '<', value: 100 }],
        score: [{ when: { field: 'rating', op: '>=', value: 4 }, add: 10 }],
        tie_break: ['price'],
        pick: 'argmax',
      },
    };
    const errors = validateRecipe(recipe);
    const polErrors = errors.filter((e) => e.file === 'policies');
    expect(polErrors).toHaveLength(0);
  });
});
