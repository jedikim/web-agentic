import { useRecipeStore } from '../store/recipeStore.ts';
import { useUiStore } from '../store/uiStore.ts';
import type { RecipeFileTab } from '../store/uiStore.ts';

const FILE_TABS: { key: RecipeFileTab; label: string }[] = [
  { key: 'workflow', label: 'workflow.json' },
  { key: 'actions', label: 'actions.json' },
  { key: 'selectors', label: 'selectors.json' },
  { key: 'fingerprints', label: 'fingerprints.json' },
  { key: 'policies', label: 'policies.json' },
];

export function FileTree() {
  const domain = useRecipeStore((s) => s.domain);
  const flow = useRecipeStore((s) => s.flow);
  const version = useRecipeStore((s) => s.version);
  const activeTab = useUiStore((s) => s.activeTab);
  const setActiveTab = useUiStore((s) => s.setActiveTab);

  return (
    <div className="file-tree">
      <div className="file-tree-header">Recipe Files</div>
      <div className="file-tree-domain">{domain}</div>
      <div className="file-tree-path">
        {flow} / {version}
      </div>
      <ul className="file-tree-list">
        {FILE_TABS.map(({ key, label }) => (
          <li
            key={key}
            className={`file-tree-item ${activeTab === key ? 'active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </li>
        ))}
      </ul>
    </div>
  );
}
