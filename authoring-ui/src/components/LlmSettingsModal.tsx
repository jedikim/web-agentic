import { useState, useEffect, useCallback } from 'react';
import { getLlmSettings, setLlmSettings, type LlmSettings, type LlmSettingsRequest } from '../utils/authoringClient.ts';

const MODELS = {
  openai: [
    { id: 'openai/gpt-5.2-codex', name: 'GPT-5.2 Codex', desc: 'Latest coding model' },
    { id: 'openai/gpt-5.2', name: 'GPT-5.2', desc: 'Flagship model' },
    { id: 'openai/gpt-5.2-pro', name: 'GPT-5.2 Pro', desc: 'Advanced reasoning' },
    { id: 'openai/o4-mini', name: 'o4-mini', desc: 'Fast reasoning' },
    { id: 'openai/gpt-4o', name: 'GPT-4o', desc: 'Stable multimodal' },
  ],
  gemini: [
    { id: 'gemini/gemini-3.1-pro-preview', name: 'Gemini 3.1 Pro', desc: 'Latest preview' },
    { id: 'gemini/gemini-3-pro-preview', name: 'Gemini 3 Pro', desc: 'Stable preview' },
    { id: 'gemini/gemini-2.5-pro', name: 'Gemini 2.5 Pro', desc: 'Production quality' },
    { id: 'gemini/gemini-2.5-flash', name: 'Gemini 2.5 Flash', desc: 'Fastest' },
  ],
};

interface Props {
  open: boolean;
  onClose: () => void;
  onConfigured: (settings: LlmSettings) => void;
  required?: boolean;
}

export function LlmSettingsModal({ open, onClose, onConfigured, required }: Props) {
  const [openaiKey, setOpenaiKey] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [selectedModel, setSelectedModel] = useState('openai/gpt-5.2-codex');
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
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [selectedModel, openaiKey, geminiKey, onClose, onConfigured]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={required ? undefined : onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{required ? 'LLM Setup Required' : 'LLM Settings'}</span>
          {!required && <button className="modal-close" onClick={onClose}>&times;</button>}
        </div>

        <div className="modal-body">
          {required && !currentSettings?.isConfigured && (
            <div className="settings-status settings-status-required">
              Please enter at least one API key to use AI recipe generation.
            </div>
          )}
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
          {!required && <button className="toolbar-btn" onClick={onClose}>Cancel</button>}
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
