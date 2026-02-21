import { useRunStore, type RunStep } from '../store/runStore.ts';
import { nodeColors } from '../nodes/nodeTypes.ts';

function formatMs(ms: number | undefined | null): string {
  if (ms == null) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const statusBadge: Record<string, { label: string; cls: string }> = {
  pending: { label: 'PENDING', cls: 'badge-pending' },
  running: { label: 'RUNNING', cls: 'badge-running' },
  passed: { label: 'PASS', cls: 'badge-passed' },
  failed: { label: 'FAIL', cls: 'badge-failed' },
};

function StepRow({ step }: { step: RunStep }) {
  const badge = statusBadge[step.status] ?? statusBadge.pending;
  const opColor = (nodeColors as Record<string, string>)[step.op] ?? '#6b7280';

  return (
    <div className="run-step-row">
      <span className="run-step-index">#{step.stepIndex + 1}</span>
      <span className="run-step-op" style={{ color: opColor }}>
        {step.op || '...'}
      </span>
      <span className="run-step-id">{step.stepId || `step-${step.stepIndex}`}</span>
      <span className={`run-step-badge ${badge.cls}`}>{badge.label}</span>
      <span className="run-step-time">{formatMs(step.durationMs)}</span>
      {step.error && <span className="run-step-error" title={step.error}>{step.error}</span>}
    </div>
  );
}

export function RunProgressPanel() {
  const status = useRunStore((s) => s.status);
  const steps = useRunStore((s) => s.steps);
  const totalDurationMs = useRunStore((s) => s.totalDurationMs);
  const error = useRunStore((s) => s.error);
  const reset = useRunStore((s) => s.reset);

  if (status === 'idle') return null;

  const headerCls =
    status === 'completed' ? 'run-header-ok' :
    status === 'failed' ? 'run-header-fail' :
    status === 'cancelled' ? 'run-header-cancel' :
    'run-header-active';

  const isDone = status === 'completed' || status === 'failed' || status === 'cancelled';

  return (
    <div className="run-progress-panel">
      <div className={`run-progress-header ${headerCls}`}>
        <span className="run-progress-title">
          {status === 'starting' && 'Starting run...'}
          {status === 'running' && 'Running...'}
          {status === 'completed' && 'Run completed'}
          {status === 'failed' && 'Run failed'}
          {status === 'cancelled' && 'Run cancelled'}
        </span>
        {totalDurationMs != null && (
          <span className="run-progress-time">Total: {formatMs(totalDurationMs)}</span>
        )}
        {isDone && (
          <button className="run-dismiss-btn" onClick={reset}>Dismiss</button>
        )}
      </div>
      {error && <div className="run-error-banner">{error}</div>}
      <div className="run-steps-list">
        {steps.map((step) => (
          <StepRow key={step.stepIndex} step={step} />
        ))}
      </div>
    </div>
  );
}
