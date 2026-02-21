import { useRunStore, type RunStep, type RunResultTab } from '../store/runStore.ts';
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

function DataTab() {
  const summary = useRunStore((s) => s.summary);
  const vars = useRunStore((s) => s.vars);
  const steps = useRunStore((s) => s.steps);

  const stepsWithData = steps.filter((s) => s.data && Object.keys(s.data).length > 0);
  const hasVars = Object.keys(vars).length > 0;

  return (
    <div className="run-data-tab">
      {summary && (
        <div className="run-summary-card">
          <div className="run-summary-header">Run Summary</div>
          <div className="run-summary-grid">
            {summary.domain && <div className="run-summary-item"><span className="run-summary-label">Domain</span><span>{summary.domain}</span></div>}
            {summary.flow && <div className="run-summary-item"><span className="run-summary-label">Flow</span><span>{summary.flow}</span></div>}
            {summary.version && <div className="run-summary-item"><span className="run-summary-label">Version</span><span>{summary.version}</span></div>}
            <div className="run-summary-item"><span className="run-summary-label">Steps</span><span>{summary.passed}/{summary.totalSteps} passed</span></div>
            {summary.failed > 0 && <div className="run-summary-item"><span className="run-summary-label">Failed</span><span className="run-summary-fail">{summary.failed}</span></div>}
          </div>
        </div>
      )}
      {stepsWithData.length > 0 && (
        <div className="run-data-section">
          <div className="run-data-section-title">Step Data</div>
          {stepsWithData.map((step) => (
            <div key={step.stepId} className="run-data-step">
              <div className="run-data-step-header">#{step.stepIndex + 1} {step.op} — {step.stepId}</div>
              <pre className="run-data-json">{JSON.stringify(step.data, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}
      {hasVars && (
        <div className="run-data-section">
          <div className="run-data-section-title">Collected Variables</div>
          <pre className="run-data-json">{JSON.stringify(vars, null, 2)}</pre>
        </div>
      )}
      {!summary && stepsWithData.length === 0 && !hasVars && (
        <div className="run-data-empty">No data collected yet</div>
      )}
    </div>
  );
}

function ScreenshotsTab() {
  const steps = useRunStore((s) => s.steps);
  const screenshots = steps.filter((s) => s.screenshot);

  if (screenshots.length === 0) {
    return <div className="run-data-empty">No screenshots captured</div>;
  }

  return (
    <div className="run-screenshots-grid">
      {screenshots.map((step) => (
        <div key={step.stepId} className="run-screenshot-card">
          <div className="run-screenshot-label">#{step.stepIndex + 1} {step.stepId}</div>
          <img
            className="run-screenshot-img"
            src={`data:image/png;base64,${step.screenshot}`}
            alt={`Screenshot: ${step.stepId}`}
          />
        </div>
      ))}
    </div>
  );
}

const TAB_LABELS: { key: RunResultTab; label: string }[] = [
  { key: 'progress', label: 'Progress' },
  { key: 'data', label: 'Data' },
  { key: 'screenshots', label: 'Screenshots' },
];

export function RunProgressPanel() {
  const status = useRunStore((s) => s.status);
  const steps = useRunStore((s) => s.steps);
  const totalDurationMs = useRunStore((s) => s.totalDurationMs);
  const error = useRunStore((s) => s.error);
  const reset = useRunStore((s) => s.reset);
  const activeResultTab = useRunStore((s) => s.activeResultTab);
  const setActiveResultTab = useRunStore((s) => s.setActiveResultTab);

  if (status === 'idle') return null;

  const headerCls =
    status === 'completed' ? 'run-header-ok' :
    status === 'failed' ? 'run-header-fail' :
    status === 'cancelled' ? 'run-header-cancel' :
    'run-header-active';

  const isDone = status === 'completed' || status === 'failed' || status === 'cancelled';

  const dataCount = steps.filter((s) => s.data && Object.keys(s.data).length > 0).length;
  const screenshotCount = steps.filter((s) => s.screenshot).length;

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
      <div className="run-tab-bar">
        {TAB_LABELS.map(({ key, label }) => {
          const count = key === 'data' ? dataCount : key === 'screenshots' ? screenshotCount : 0;
          return (
            <button
              key={key}
              className={`run-tab ${activeResultTab === key ? 'run-tab-active' : ''}`}
              onClick={() => setActiveResultTab(key)}
            >
              {label}
              {count > 0 && <span className="run-tab-count">{count}</span>}
            </button>
          );
        })}
      </div>
      <div className="run-tab-content">
        {activeResultTab === 'progress' && (
          <div className="run-steps-list">
            {steps.map((step) => (
              <StepRow key={step.stepIndex} step={step} />
            ))}
          </div>
        )}
        {activeResultTab === 'data' && <DataTab />}
        {activeResultTab === 'screenshots' && <ScreenshotsTab />}
      </div>
    </div>
  );
}
