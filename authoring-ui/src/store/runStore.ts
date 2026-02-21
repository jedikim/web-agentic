import { create } from 'zustand';

export type RunStatus = 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'cancelled';
export type StepRunStatus = 'pending' | 'running' | 'passed' | 'failed';

export interface RunStep {
  stepId: string;
  stepIndex: number;
  op: string;
  status: StepRunStatus;
  durationMs?: number;
  error?: string;
}

interface RunState {
  status: RunStatus;
  runId: string | null;
  steps: RunStep[];
  totalDurationMs: number | null;
  error: string | null;
}

interface RunActions {
  setStarting: () => void;
  setRunStart: (runId: string, totalSteps: number) => void;
  setStepStart: (stepId: string, stepIndex: number, op: string) => void;
  setStepEnd: (stepId: string, ok: boolean, durationMs: number, error?: string) => void;
  setRunComplete: (ok: boolean, totalDurationMs: number) => void;
  setRunError: (error: string) => void;
  cancelRun: () => void;
  reset: () => void;
}

export type RunStore = RunState & RunActions;

const initialState: RunState = {
  status: 'idle',
  runId: null,
  steps: [],
  totalDurationMs: null,
  error: null,
};

export const useRunStore = create<RunStore>((set) => ({
  ...initialState,

  setStarting: () => set({ status: 'starting', error: null, steps: [], runId: null, totalDurationMs: null }),

  setRunStart: (runId, totalSteps) =>
    set({
      status: 'running',
      runId,
      steps: Array.from({ length: totalSteps }, (_, i) => ({
        stepId: '',
        stepIndex: i,
        op: '',
        status: 'pending' as StepRunStatus,
      })),
    }),

  setStepStart: (stepId, stepIndex, op) =>
    set((state) => ({
      steps: state.steps.map((s, i) =>
        i === stepIndex ? { ...s, stepId, op, status: 'running' as StepRunStatus } : s,
      ),
    })),

  setStepEnd: (stepId, ok, durationMs, error) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.stepId === stepId
          ? { ...s, status: (ok ? 'passed' : 'failed') as StepRunStatus, durationMs, error }
          : s,
      ),
    })),

  setRunComplete: (ok, totalDurationMs) =>
    set({ status: ok ? 'completed' : 'failed', totalDurationMs }),

  setRunError: (error) => set({ status: 'failed', error }),

  cancelRun: () => set({ status: 'cancelled' }),

  reset: () => set(initialState),
}));
