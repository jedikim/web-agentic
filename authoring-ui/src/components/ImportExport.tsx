import { useRef } from 'react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { importFromFiles } from '../utils/importRecipe.ts';
import { exportRecipeZip, exportJsonFile } from '../utils/exportRecipe.ts';
import { useUiStore } from '../store/uiStore.ts';

export function ImportExport() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const importRecipe = useRecipeStore((s) => s.importRecipe);
  const exportRecipe = useRecipeStore((s) => s.exportRecipe);
  const domain = useRecipeStore((s) => s.domain);
  const version = useRecipeStore((s) => s.version);
  const resetToDefault = useRecipeStore((s) => s.resetToDefault);
  const activeTab = useUiStore((s) => s.activeTab);

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

  const handleExportFile = () => {
    const recipe = exportRecipe();
    const data = recipe[activeTab];
    exportJsonFile(data, `${activeTab}.json`);
  };

  return (
    <div className="import-export">
      <button className="toolbar-btn" onClick={resetToDefault}>New</button>
      <button className="toolbar-btn" onClick={() => fileInputRef.current?.click()}>Import</button>
      <button className="toolbar-btn" onClick={handleExportZip}>Export ZIP</button>
      <button className="toolbar-btn" onClick={handleExportFile}>Export {activeTab}.json</button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.zip"
        multiple
        onChange={handleImport}
        style={{ display: 'none' }}
      />
    </div>
  );
}
