import { describe, it, expect, beforeEach } from 'vitest';
import { useRecipeStore } from '../store/recipeStore.ts';

describe('recipeStore', () => {
  beforeEach(() => {
    useRecipeStore.getState().resetToDefault();
  });

  it('initializes with default workflow', () => {
    const state = useRecipeStore.getState();
    expect(state.workflow.id).toBe('new-workflow');
    expect(state.workflow.steps).toHaveLength(1);
    expect(state.workflow.steps[0].op).toBe('goto');
  });

  it('addStep appends a step', () => {
    useRecipeStore.getState().addStep({
      id: 'step-2',
      op: 'act_cached',
      targetKey: 'some_key',
    });
    const state = useRecipeStore.getState();
    expect(state.workflow.steps).toHaveLength(2);
    expect(state.workflow.steps[1].id).toBe('step-2');
    expect(state.isDirty).toBe(true);
  });

  it('updateStep modifies a step', () => {
    useRecipeStore.getState().updateStep('step-1', { op: 'wait', args: { ms: 1000 } });
    const state = useRecipeStore.getState();
    expect(state.workflow.steps[0].op).toBe('wait');
    expect(state.workflow.steps[0].args).toEqual({ ms: 1000 });
  });

  it('removeStep removes a step', () => {
    useRecipeStore.getState().addStep({ id: 'step-2', op: 'wait' });
    useRecipeStore.getState().removeStep('step-1');
    const state = useRecipeStore.getState();
    expect(state.workflow.steps).toHaveLength(1);
    expect(state.workflow.steps[0].id).toBe('step-2');
  });

  it('reorderSteps moves a step', () => {
    useRecipeStore.getState().addStep({ id: 'step-2', op: 'wait' });
    useRecipeStore.getState().addStep({ id: 'step-3', op: 'checkpoint' });
    useRecipeStore.getState().reorderSteps(0, 2);
    const state = useRecipeStore.getState();
    expect(state.workflow.steps.map((s) => s.id)).toEqual(['step-2', 'step-3', 'step-1']);
  });

  it('setActions updates actions', () => {
    useRecipeStore.getState().setActions({
      click_link: {
        instruction: 'Click the link',
        preferred: { selector: '#link', description: 'link', method: 'click', arguments: null },
        observedAt: '2026-01-01',
      },
    });
    const state = useRecipeStore.getState();
    expect(Object.keys(state.actions)).toContain('click_link');
    expect(state.isDirty).toBe(true);
  });

  it('importRecipe sets recipe data and clears dirty', () => {
    useRecipeStore.getState().addStep({ id: 'x', op: 'wait' }); // make dirty
    expect(useRecipeStore.getState().isDirty).toBe(true);

    useRecipeStore.getState().importRecipe({
      workflow: { id: 'imported', version: 'v002', steps: [{ id: 's1', op: 'goto' }] },
    });
    const state = useRecipeStore.getState();
    expect(state.workflow.id).toBe('imported');
    expect(state.isDirty).toBe(false);
  });

  it('exportRecipe returns all recipe parts', () => {
    const exported = useRecipeStore.getState().exportRecipe();
    expect(exported).toHaveProperty('workflow');
    expect(exported).toHaveProperty('actions');
    expect(exported).toHaveProperty('selectors');
    expect(exported).toHaveProperty('fingerprints');
    expect(exported).toHaveProperty('policies');
  });

  it('resetToDefault restores initial state', () => {
    useRecipeStore.getState().addStep({ id: 'x', op: 'wait' });
    useRecipeStore.getState().resetToDefault();
    const state = useRecipeStore.getState();
    expect(state.workflow.steps).toHaveLength(1);
    expect(state.isDirty).toBe(false);
  });
});
