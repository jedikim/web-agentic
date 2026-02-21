import { useRef, useState, useEffect } from 'react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { useValidation } from '../hooks/useValidation.ts';
import { importFromFiles } from '../utils/importRecipe.ts';
import { exportRecipeZip } from '../utils/exportRecipe.ts';
import { nodeColors, nodeLabels } from '../nodes/nodeTypes.ts';
import type { WorkflowStep } from '../validation/schemas.ts';
import { LlmSettingsModal } from './LlmSettingsModal.tsx';
import { getLlmSettings, type LlmSettings } from '../utils/authoringClient.ts';

const STEP_TYPES = ['goto', 'act_cached', 'checkpoint', 'extract', 'wait'] as const;

function makeId(): string {
  return `step-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function createDefaultStep(op: WorkflowStep['op']): WorkflowStep {
  const id = makeId();
  switch (op) {
    case 'goto':
      return { id, op, args: { url: 'https://' } };
    case 'act_cached':
      return { id, op, targetKey: '' };
    case 'checkpoint':
      return { id, op, args: { message: '' } };
    case 'extract':
      return { id, op, args: { scope: '' } };
    case 'wait':
      return { id, op, args: { ms: 1000 } };
    default:
      return { id, op };
  }
}

export function Toolbar() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addStep = useRecipeStore((s) => s.addStep);
  const resetToDefault = useRecipeStore((s) => s.resetToDefault);
  const importRecipe = useRecipeStore((s) => s.importRecipe);
  const exportRecipe = useRecipeStore((s) => s.exportRecipe);
  const domain = useRecipeStore((s) => s.domain);
  const version = useRecipeStore((s) => s.version);
  const { isValid, errorCount } = useValidation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmSettings, setLlmSettings] = useState<LlmSettings | null>(null);
  const [checkedOnMount, setCheckedOnMount] = useState(false);

  // Check LLM settings on mount — auto-open modal if not configured
  useEffect(() => {
    getLlmSettings()
      .then((s) => {
        setLlmSettings(s);
        if (!s.isConfigured) setSettingsOpen(true);
        setCheckedOnMount(true);
      })
      .catch(() => {
        // Service offline — still open modal so user knows they need to configure
        setSettingsOpen(true);
        setCheckedOnMount(true);
      });
  }, []);

  const handleAddStep = (op: WorkflowStep['op']) => {
    addStep(createDefaultStep(op));
  };

  const handleDragStart = (e: React.DragEvent, op: string) => {
    e.dataTransfer.setData('application/reactflow-type', op);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const result = await importFromFiles(files);
    importRecipe(result);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleExportZip = async () => {
    const recipe = exportRecipe();
    await exportRecipeZip(
      recipe as { workflow: unknown; actions: unknown; selectors: unknown; fingerprints: unknown; policies: unknown },
      domain,
      version,
    );
  };

  return (
    <header className="toolbar">
      <div className="toolbar-left">
        <span className="toolbar-title">Recipe Editor</span>
        <div className="toolbar-steps">
          {STEP_TYPES.map((op) => (
            <button
              key={op}
              className="toolbar-btn toolbar-step-btn"
              style={{ borderColor: nodeColors[op] }}
              draggable
              onDragStart={(e) => handleDragStart(e, op)}
              onClick={() => handleAddStep(op)}
            >
              + {nodeLabels[op]}
            </button>
          ))}
        </div>
      </div>
      <div className="toolbar-right">
        <button
          className={`toolbar-btn ${llmSettings?.isConfigured ? 'toolbar-btn-valid' : ''}`}
          onClick={() => setSettingsOpen(true)}
          title={llmSettings?.isConfigured ? `LLM: ${llmSettings.model}` : 'Configure LLM'}
        >
          {llmSettings?.isConfigured ? `LLM: ${llmSettings.model?.split('/')[1]}` : 'LLM Settings'}
        </button>
        <button className="toolbar-btn" onClick={resetToDefault}>New Recipe</button>
        <button className="toolbar-btn" onClick={() => fileInputRef.current?.click()}>Import...</button>
        <button className="toolbar-btn" onClick={handleExportZip}>Export ZIP</button>
        <button
          className={`toolbar-btn ${isValid ? 'toolbar-btn-valid' : 'toolbar-btn-invalid'}`}
          title={isValid ? 'Recipe is valid' : `${errorCount} validation error(s)`}
          disabled
        >
          {isValid ? 'Valid' : `${errorCount} Error${errorCount !== 1 ? 's' : ''}`}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.zip"
          multiple
          onChange={handleImport}
          style={{ display: 'none' }}
        />
      </div>
      <LlmSettingsModal
        open={settingsOpen}
        onClose={() => { if (llmSettings?.isConfigured) setSettingsOpen(false); }}
        onConfigured={(s) => { setLlmSettings(s); if (s.isConfigured) setSettingsOpen(false); }}
        required={!llmSettings?.isConfigured}
      />
    </header>
  );
}
