import { useState, useEffect, useCallback } from 'react';
import { getLlmSettings, setLlmSettings, type LlmSettings, type LlmSettingsRequest } from '../utils/authoringClient.ts';

const MODELS = {
  openai: [
    { id: 'openai/gpt-4o', name: 'GPT-4o', desc: 'Flagship multimodal' },
    { id: 'openai/gpt-4o-mini', name: 'GPT-4o Mini', desc: 'Fast and affordable' },
    { id: 'openai/o3-mini', name: 'o3-mini', desc: 'Reasoning model' },
  ],
  gemini: [
    { id: 'gemini/gemini-2.5-flash', name: 'Gemini 2.5 Flash', desc: 'Fastest' },
    { id: 'gemini/gemini-2.0-flash', name: 'Gemini 2.0 Flash', desc: 'Stable' },
    { id: 'gemini/gemini-2.5-pro', name: 'Gemini 2.5 Pro', desc: 'Best quality' },
  ],
};

interface Props {
  open: boolean;
  onClose: () => void;
  onConfigured: (settings: LlmSettings) => void;
}

export function LlmSettingsModal({ open, onClose, onConfigured }: Props) {
  const [openaiKey, setOpenaiKey] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [selectedModel, setSelectedModel] = useState('openai/gpt-4o');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentSettings, setCurrentSettings] = useState<LlmSettings | null>(null);

  useEffect(() => {
    if (open) {
      getLlmSettings().then((s) => {
        setCurrentSettings(s);
        if (s.model) setSelectedModel(s.model);
      }).catch(() => {});
    }
  }, [open]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const req: LlmSettingsRequest = { model: selectedModel };
      if (openaiKey) req.openai_api_key = openaiKey;
      if (geminiKey) req.gemini_api_key = geminiKey;
      const result = await setLlmSettings(req);
      setCurrentSettings(result);
      onConfigured(result);
      if (result.isConfigured) {
        setOpenaiKey('');
        setGeminiKey('');
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [selectedModel, openaiKey, geminiKey, onClose, onConfigured]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">LLM Settings</span>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          {currentSettings?.isConfigured && (
            <div className="settings-status settings-status-ok">
              Active: {currentSettings.model}
            </div>
          )}

          <div className="settings-section">
            <label className="settings-label">OpenAI API Key</label>
            <input
              type="password"
              className="settings-input"
              placeholder={currentSettings?.openaiKeyMasked || 'sk-...'}
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
            />
            {currentSettings?.openaiKeySet && !openaiKey && (
              <span className="settings-hint">Key saved ({currentSettings.openaiKeyMasked})</span>
            )}
          </div>

          <div className="settings-section">
            <label className="settings-label">Gemini API Key</label>
            <input
              type="password"
              className="settings-input"
              placeholder={currentSettings?.geminiKeyMasked || 'AI...'}
              value={geminiKey}
              onChange={(e) => setGeminiKey(e.target.value)}
            />
            {currentSettings?.geminiKeySet && !geminiKey && (
              <span className="settings-hint">Key saved ({currentSettings.geminiKeyMasked})</span>
            )}
          </div>

          <div className="settings-section">
            <label className="settings-label">Model</label>
            <select
              className="settings-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              <optgroup label="OpenAI">
                {MODELS.openai.map((m) => (
                  <option key={m.id} value={m.id}>{m.name} — {m.desc}</option>
                ))}
              </optgroup>
              <optgroup label="Gemini">
                {MODELS.gemini.map((m) => (
                  <option key={m.id} value={m.id}>{m.name} — {m.desc}</option>
                ))}
              </optgroup>
            </select>
          </div>

          {error && <div className="settings-error">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="toolbar-btn" onClick={onClose}>Cancel</button>
          <button
            className="chat-send-btn"
            onClick={handleSave}
            disabled={saving || (!openaiKey && !geminiKey && !currentSettings?.openaiKeySet && !currentSettings?.geminiKeySet)}
          >
            {saving ? 'Saving...' : 'Save & Apply'}
          </button>
        </div>
      </div>
    </div>
  );
}
