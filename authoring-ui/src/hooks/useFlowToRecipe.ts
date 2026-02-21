import { useCallback } from 'react';
import type { Node } from '@xyflow/react';
import { useRecipeStore } from '../store/recipeStore.ts';
import type { WorkflowStep } from '../validation/schemas.ts';

export function nodesToStepOrder(nodes: Node[]): string[] {
  return [...nodes]
    .sort((a, b) => a.position.x - b.position.x)
    .map((n) => n.id);
}

export function useFlowToRecipe() {
  const steps = useRecipeStore((s) => s.workflow.steps);
  const setWorkflow = useRecipeStore((s) => s.setWorkflow);
  const workflow = useRecipeStore((s) => s.workflow);

  const syncNodeOrder = useCallback(
    (nodes: Node[]) => {
      const newOrder = nodesToStepOrder(nodes);
      const currentOrder = steps.map((s) => s.id);

      if (JSON.stringify(newOrder) === JSON.stringify(currentOrder)) return;

      const stepMap = new Map<string, WorkflowStep>();
      for (const step of steps) {
        stepMap.set(step.id, step);
      }

      const reordered = newOrder
        .map((id) => stepMap.get(id))
        .filter((s): s is WorkflowStep => s != null);

      if (reordered.length === steps.length) {
        setWorkflow({ ...workflow, steps: reordered });
      }
    },
    [steps, workflow, setWorkflow],
  );

  return { syncNodeOrder };
}
