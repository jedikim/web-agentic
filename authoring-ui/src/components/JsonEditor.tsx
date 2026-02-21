import { useCallback, useRef } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { useUiStore } from '../store/uiStore.ts';
import type { RecipeFileTab } from '../store/uiStore.ts';

function getFileContent(store: ReturnType<typeof useRecipeStore.getState>, tab: RecipeFileTab): string {
  const data = store[tab];
  return JSON.stringify(data, null, 2);
}

export function JsonEditor() {
  const activeTab = useUiStore((s) => s.activeTab);
  const store = useRecipeStore();
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  const content = getFileContent(store, activeTab);

  const handleMount: OnMount = (editor) => {
    editorRef.current = editor;
  };

  const handleChange = useCallback(
    (value: string | undefined) => {
      if (!value) return;
      try {
        const parsed = JSON.parse(value) as unknown;
        const setters: Record<RecipeFileTab, (data: never) => void> = {
          workflow: store.setWorkflow,
          actions: store.setActions,
          selectors: store.setSelectors,
          fingerprints: store.setFingerprints,
          policies: store.setPolicies,
        };
        setters[activeTab](parsed as never);
      } catch {
        // Invalid JSON - ignore until valid
      }
    },
    [activeTab, store],
  );

  return (
    <div className="json-editor">
      <div className="json-editor-header">{activeTab}.json</div>
      <Editor
        height="100%"
        language="json"
        theme="vs-dark"
        value={content}
        onChange={handleChange}
        onMount={handleMount}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: 'on',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
        }}
      />
    </div>
  );
}
