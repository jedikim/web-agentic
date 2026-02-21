import type { Expectation } from '../validation/schemas.ts';

const EXPECTATION_KINDS: Expectation['kind'][] = [
  'url_contains',
  'title_contains',
  'selector_visible',
  'text_contains',
];

interface ExpectationEditorProps {
  expectations: Expectation[];
  onChange: (expectations: Expectation[]) => void;
}

export function ExpectationEditor({ expectations, onChange }: ExpectationEditorProps) {
  const updateRow = (index: number, patch: Partial<Expectation>) => {
    const updated = expectations.map((exp, i) =>
      i === index ? { ...exp, ...patch } : exp,
    );
    onChange(updated);
  };

  const addRow = () => {
    onChange([...expectations, { kind: 'url_contains', value: '' }]);
  };

  const removeRow = (index: number) => {
    onChange(expectations.filter((_, i) => i !== index));
  };

  return (
    <div className="expectation-editor">
      <label className="prop-label">Expectations</label>
      {expectations.map((exp, i) => (
        <div key={i} className="expectation-row">
          <select
            className="prop-select"
            value={exp.kind}
            onChange={(e) => updateRow(i, { kind: e.target.value as Expectation['kind'] })}
          >
            {EXPECTATION_KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
          <input
            className="prop-input"
            type="text"
            value={exp.value}
            onChange={(e) => updateRow(i, { value: e.target.value })}
            placeholder="value"
          />
          <button className="prop-btn-remove" onClick={() => removeRow(i)} title="Remove">x</button>
        </div>
      ))}
      <button className="prop-btn-add" onClick={addRow}>+ Add</button>
    </div>
  );
}
