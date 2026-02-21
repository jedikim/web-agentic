import { create } from 'zustand';

export type RunStatus = 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'cancelled';
export type StepRunStatus = 'pending' | 'running' | 'passed' | 'failed';
export type RunResultTab = 'progress' | 'data' | 'screenshots';

export interface RunStep {
  stepId: string;
  stepIndex: number;
  op: string;
  status: StepRunStatus;
  durationMs?: number;
  error?: string;
  data?: Record<string, unknown>;
  screenshot?: string;
}

export interface RunSummary {
  totalSteps: number;
  passed: number;
  failed: number;
  domain: string;
  flow: string;
  version: string;
}

interface RunState {
  status: RunStatus;
  runId: string | null;
  steps: RunStep[];
  totalDurationMs: number | null;
  error: string | null;
  vars: Record<string, unknown>;
  summary: RunSummary | null;
  activeResultTab: RunResultTab;
}

interface RunActions {
  setStarting: () => void;
  setRunStart: (runId: string, totalSteps: number) => void;
  setStepStart: (stepId: string, stepIndex: number, op: string) => void;
  setStepEnd: (stepId: string, ok: boolean, durationMs: number, opts?: {
    error?: string;
    data?: Record<string, unknown>;
    screenshot?: string;
  }) => void;
  setRunComplete: (ok: boolean, totalDurationMs: number, vars?: Record<string, unknown>, summary?: RunSummary) => void;
  setRunError: (error: string) => void;
  setActiveResultTab: (tab: RunResultTab) => void;
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
  vars: {},
  summary: null,
  activeResultTab: 'progress',
};

export const useRunStore = create<RunStore>((set) => ({
  ...initialState,

  setStarting: () => set({ ...initialState, status: 'starting' }),

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

  setStepEnd: (stepId, ok, durationMs, opts) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.stepId === stepId
          ? {
              ...s,
              status: (ok ? 'passed' : 'failed') as StepRunStatus,
              durationMs,
              error: opts?.error,
              data: opts?.data,
              screenshot: opts?.screenshot,
            }
          : s,
      ),
      vars: opts?.data ? { ...state.vars, ...opts.data } : state.vars,
    })),

  setRunComplete: (ok, totalDurationMs, vars, summary) =>
    set((state) => ({
      status: ok ? 'completed' : 'failed',
      totalDurationMs,
      vars: vars ?? state.vars,
      summary: summary ?? state.summary,
    })),

  setRunError: (error) => set({ status: 'failed', error }),

  setActiveResultTab: (tab) => set({ activeResultTab: tab }),

  cancelRun: () => set({ status: 'cancelled' }),

  reset: () => set(initialState),
}));
