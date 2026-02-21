import { useCallback, useRef } from 'react';
import { useRunStore } from '../store/runStore.ts';
import { useRecipeStore } from '../store/recipeStore.ts';
import {
  startRunRecipe,
  createRunEventSource,
  cancelRun as apiCancelRun,
} from '../utils/authoringClient.ts';

export function useRunRecipe() {
  const esRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | null>(null);

  const status = useRunStore((s) => s.status);
  const store = useRunStore;

  const startRun = useCallback(async () => {
    const recipe = useRecipeStore.getState().exportRecipe();

    store.getState().setStarting();

    try {
      const { runId } = await startRunRecipe(recipe);
      runIdRef.current = runId;

      const es = createRunEventSource(runId);
      esRef.current = es;

      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const state = store.getState();

          switch (data.type) {
            case 'run_start':
              state.setRunStart(data.runId, data.totalSteps);
              break;
            case 'step_start':
              state.setStepStart(data.stepId, data.stepIndex, data.op);
              break;
            case 'step_end':
              state.setStepEnd(data.stepId, data.ok, data.durationMs, {
                error: data.message,
                data: data.data,
                screenshot: data.screenshot,
              });
              break;
            case 'run_complete':
              state.setRunComplete(data.ok, data.totalDurationMs, data.vars, data.summary);
              es.close();
              esRef.current = null;
              break;
            case 'run_error':
              state.setRunError(data.error);
              es.close();
              esRef.current = null;
              break;
          }
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        const state = store.getState();
        if (state.status === 'running' || state.status === 'starting') {
          state.setRunError('Connection to run stream lost');
        }
        es.close();
        esRef.current = null;
      };
    } catch (err) {
      store.getState().setRunError(
        err instanceof Error ? err.message : 'Failed to start run',
      );
    }
  }, [store]);

  const cancelRunAction = useCallback(async () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (runIdRef.current) {
      try {
        await apiCancelRun(runIdRef.current);
      } catch {
        // best-effort cancel
      }
    }
    store.getState().cancelRun();
  }, [store]);

  return { startRun, cancelRun: cancelRunAction, status };
}
