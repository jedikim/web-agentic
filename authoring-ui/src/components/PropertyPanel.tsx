import { useUiStore } from '../store/uiStore.ts';
import { useRecipeStore } from '../store/recipeStore.ts';
import { ExpectationEditor } from './ExpectationEditor.tsx';
import type { WorkflowStep, Expectation } from '../validation/schemas.ts';

function getArgs(step: WorkflowStep): Record<string, unknown> {
  return (step.args as Record<string, unknown>) ?? {};
}

export function PropertyPanel() {
  const selectedNodeId = useUiStore((s) => s.selectedNodeId);
  const steps = useRecipeStore((s) => s.workflow.steps);
  const updateStep = useRecipeStore((s) => s.updateStep);
  const actions = useRecipeStore((s) => s.actions);

  const step = steps.find((s) => s.id === selectedNodeId);

  if (!step) {
    return (
      <div className="property-panel">
        <div className="panel-header">Properties</div>
        <p className="panel-hint">Select a node to edit its properties</p>
      </div>
    );
  }

  const args = getArgs(step);
  const actionKeys = Object.keys(actions);

  const setArg = (key: string, value: unknown) => {
    updateStep(step.id, { args: { ...args, [key]: value } });
  };

  const setField = (key: keyof WorkflowStep, value: unknown) => {
    updateStep(step.id, { [key]: value });
  };

  return (
    <div className="property-panel">
      <div className="panel-header">Properties — {step.op}</div>
      <div className="panel-body">
        <div className="prop-group">
          <label className="prop-label">Step ID</label>
          <input className="prop-input" type="text" value={step.id} readOnly />
        </div>

        {step.op === 'goto' && (
          <div className="prop-group">
            <label className="prop-label">URL</label>
            <input
              className="prop-input"
              type="text"
              value={(args.url as string) ?? ''}
              onChange={(e) => setArg('url', e.target.value)}
              placeholder="https://example.com"
            />
          </div>
        )}

        {step.op === 'act_cached' && (
          <>
            <div className="prop-group">
              <label className="prop-label">Target Key</label>
              <input
                className="prop-input"
                type="text"
                list="action-keys-list"
                value={step.targetKey ?? ''}
                onChange={(e) => setField('targetKey', e.target.value || null)}
                placeholder="action_key"
              />
              <datalist id="action-keys-list">
                {actionKeys.map((k) => (
                  <option key={k} value={k} />
                ))}
              </datalist>
            </div>
            <div className="prop-group">
              <label className="prop-label">On Fail</label>
              <select
                className="prop-select"
                value={step.onFail ?? ''}
                onChange={(e) => setField('onFail', e.target.value || null)}
              >
                <option value="">(none)</option>
                <option value="retry">retry</option>
                <option value="fallback">fallback</option>
                <option value="checkpoint">checkpoint</option>
                <option value="abort">abort</option>
              </select>
            </div>
          </>
        )}

        {step.op === 'checkpoint' && (
          <div className="prop-group">
            <label className="prop-label">Message</label>
            <input
              className="prop-input"
              type="text"
              value={(args.message as string) ?? ''}
              onChange={(e) => setArg('message', e.target.value)}
              placeholder="Checkpoint message"
            />
          </div>
        )}

        {step.op === 'extract' && (
          <div className="prop-group">
            <label className="prop-label">Scope</label>
            <input
              className="prop-input"
              type="text"
              value={(args.scope as string) ?? ''}
              onChange={(e) => setArg('scope', e.target.value)}
              placeholder="(empty = full page)"
            />
          </div>
        )}

        {step.op === 'wait' && (
          <div className="prop-group">
            <label className="prop-label">Duration (ms)</label>
            <input
              className="prop-input"
              type="number"
              value={(args.ms as number) ?? 0}
              onChange={(e) => setArg('ms', parseInt(e.target.value, 10) || 0)}
              min={0}
              step={100}
            />
          </div>
        )}

        {(step.op === 'checkpoint' || step.op === 'act_cached') && (
          <ExpectationEditor
            expectations={(step.expect as Expectation[]) ?? []}
            onChange={(exps) => setField('expect', exps.length > 0 ? exps : null)}
          />
        )}
      </div>
    </div>
  );
}
