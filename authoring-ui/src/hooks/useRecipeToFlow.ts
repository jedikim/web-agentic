import { useMemo } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { useUiStore } from '../store/uiStore.ts';
import { useRunStore, type StepRunStatus } from '../store/runStore.ts';
import type { WorkflowStep } from '../validation/schemas.ts';

const NODE_SPACING_X = 280;
const NODE_Y = 100;

export function stepsToNodes(
  steps: WorkflowStep[],
  errorStepIds: Set<string>,
  runStatusMap?: Map<string, StepRunStatus>,
): Node[] {
  return steps.map((step, index) => ({
    id: step.id,
    type: step.op,
    position: { x: index * NODE_SPACING_X, y: NODE_Y },
    data: {
      step,
      hasError: errorStepIds.has(step.id),
      runStatus: runStatusMap?.get(step.id),
    },
  }));
}

export function stepsToEdges(steps: WorkflowStep[]): Edge[] {
  const edges: Edge[] = [];
  for (let i = 0; i < steps.length - 1; i++) {
    edges.push({
      id: `e-${steps[i].id}-${steps[i + 1].id}`,
      source: steps[i].id,
      target: steps[i + 1].id,
      type: 'smoothstep',
    });
  }
  return edges;
}

export function useRecipeToFlow() {
  const steps = useRecipeStore((s) => s.workflow.steps);
  const validationErrors = useUiStore((s) => s.validationErrors);
  const runSteps = useRunStore((s) => s.steps);
  const runStatus = useRunStore((s) => s.status);

  const errorStepIds = useMemo(() => {
    const ids = new Set<string>();
    for (const err of validationErrors) {
      if (err.file === 'workflow' && err.path.startsWith('steps.')) {
        const stepId = err.path.split('.')[1];
        if (stepId) ids.add(stepId);
      }
    }
    return ids;
  }, [validationErrors]);

  const runStatusMap = useMemo(() => {
    if (runStatus === 'idle') return undefined;
    const map = new Map<string, StepRunStatus>();
    for (const rs of runSteps) {
      if (rs.stepId) map.set(rs.stepId, rs.status);
    }
    return map;
  }, [runSteps, runStatus]);

  const nodes = useMemo(
    () => stepsToNodes(steps, errorStepIds, runStatusMap),
    [steps, errorStepIds, runStatusMap],
  );
  const edges = useMemo(() => stepsToEdges(steps), [steps]);

  return { nodes, edges };
}
