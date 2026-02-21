import { create } from 'zustand';
import type { Workflow, WorkflowStep, ActionsMap, SelectorsMap, FingerprintsMap, PoliciesMap } from '../validation/schemas.ts';
import { createDefaultRecipe } from '../utils/recipeDefaults.ts';
import type { RecipeSnapshot } from './projectTypes.ts';

interface RecipeState {
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  fingerprints: FingerprintsMap;
  policies: PoliciesMap;
  domain: string;
  flow: string;
  version: string;
  isDirty: boolean;
}

interface RecipeActions {
  setWorkflow: (wf: Workflow) => void;
  addStep: (step: WorkflowStep) => void;
  updateStep: (id: string, patch: Partial<WorkflowStep>) => void;
  removeStep: (id: string) => void;
  reorderSteps: (from: number, to: number) => void;
  setActions: (actions: ActionsMap) => void;
  setSelectors: (selectors: SelectorsMap) => void;
  setFingerprints: (fp: FingerprintsMap) => void;
  setPolicies: (pol: PoliciesMap) => void;
  importRecipe: (files: Record<string, unknown>) => void;
  exportRecipe: () => Record<string, unknown>;
  resetToDefault: () => void;
  getSnapshot: () => RecipeSnapshot;
  loadSnapshot: (snap: RecipeSnapshot) => void;
}

export type RecipeStore = RecipeState & RecipeActions;

const defaults = createDefaultRecipe();

const initialState: RecipeState = {
  workflow: defaults.workflow,
  actions: defaults.actions,
  selectors: defaults.selectors,
  fingerprints: defaults.fingerprints,
  policies: defaults.policies,
  domain: 'example.com',
  flow: 'default',
  version: 'v001',
  isDirty: false,
};

export const useRecipeStore = create<RecipeStore>((set, get) => ({
  ...initialState,

  setWorkflow: (wf) => set({ workflow: wf, isDirty: true }),

  addStep: (step) =>
    set((state) => ({
      workflow: { ...state.workflow, steps: [...state.workflow.steps, step] },
      isDirty: true,
    })),

  updateStep: (id, patch) =>
    set((state) => ({
      workflow: {
        ...state.workflow,
        steps: state.workflow.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)),
      },
      isDirty: true,
    })),

  removeStep: (id) =>
    set((state) => ({
      workflow: {
        ...state.workflow,
        steps: state.workflow.steps.filter((s) => s.id !== id),
      },
      isDirty: true,
    })),

  reorderSteps: (from, to) =>
    set((state) => {
      const steps = [...state.workflow.steps];
      const [moved] = steps.splice(from, 1);
      steps.splice(to, 0, moved);
      return { workflow: { ...state.workflow, steps }, isDirty: true };
    }),

  setActions: (actions) => set({ actions, isDirty: true }),
  setSelectors: (selectors) => set({ selectors, isDirty: true }),
  setFingerprints: (fingerprints) => set({ fingerprints, isDirty: true }),
  setPolicies: (policies) => set({ policies, isDirty: true }),

  importRecipe: (files) => {
    const update: Partial<RecipeState> = { isDirty: false };
    if (files.workflow) update.workflow = files.workflow as Workflow;
    if (files.actions) update.actions = files.actions as ActionsMap;
    if (files.selectors) update.selectors = files.selectors as SelectorsMap;
    if (files.fingerprints) update.fingerprints = files.fingerprints as FingerprintsMap;
    if (files.policies) update.policies = files.policies as PoliciesMap;
    set(update);
  },

  exportRecipe: () => {
    const state = get();
    return {
      workflow: state.workflow,
      actions: state.actions,
      selectors: state.selectors,
      fingerprints: state.fingerprints,
      policies: state.policies,
    };
  },

  resetToDefault: () => {
    const defaults = createDefaultRecipe();
    set({
      ...defaults,
      domain: 'example.com',
      flow: 'default',
      version: 'v001',
      isDirty: false,
    });
  },

  getSnapshot: () => {
    const s = get();
    return {
      workflow: s.workflow,
      actions: s.actions,
      selectors: s.selectors,
      fingerprints: s.fingerprints,
      policies: s.policies,
      domain: s.domain,
      flow: s.flow,
      version: s.version,
    };
  },

  loadSnapshot: (snap) => {
    set({ ...snap, isDirty: false });
  },
}));
