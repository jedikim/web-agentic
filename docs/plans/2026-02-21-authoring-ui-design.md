# Recipe Visual Flow Editor — Design Document

**Date:** 2026-02-21
**Tech Stack:** React 18 + Vite + TypeScript + React Flow + Zustand + Monaco Editor

---

## Overview

A web-based visual authoring tool for creating and editing web-agentic recipes. Users interact with a node-based flow editor (React Flow) where each workflow step is a draggable node. A property panel allows editing node details, and import/export supports the 5-file recipe format.

## Architecture

```
authoring-ui/                          # Standalone SPA (no backend needed)
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── public/
│   └── favicon.svg
└── src/
    ├── main.tsx                       # Entry point
    ├── App.tsx                        # Layout: Toolbar + FileTree + Canvas + Panel
    ├── components/
    │   ├── FlowCanvas.tsx             # React Flow canvas with custom nodes
    │   ├── Toolbar.tsx                # Step type buttons + recipe actions
    │   ├── PropertyPanel.tsx          # Selected node property editor
    │   ├── FileTree.tsx               # Recipe file list (5 JSON tabs)
    │   ├── JsonEditor.tsx             # Monaco editor for raw JSON
    │   ├── ImportExport.tsx           # Import/export buttons + logic
    │   ├── ValidationStatus.tsx       # Zod validation display
    │   └── ExpectationEditor.tsx      # Sub-editor for expect[] arrays
    ├── nodes/
    │   ├── GotoNode.tsx               # Blue - url field
    │   ├── ActCachedNode.tsx          # Green - targetKey, onFail
    │   ├── CheckpointNode.tsx         # Orange - message, expects
    │   ├── ExtractNode.tsx            # Purple - schema, scope
    │   ├── WaitNode.tsx               # Gray - ms
    │   └── nodeTypes.ts               # Registry + color map
    ├── store/
    │   ├── recipeStore.ts             # Zustand: full recipe state
    │   └── uiStore.ts                 # Zustand: selected node, active tab, etc.
    ├── hooks/
    │   ├── useRecipeToFlow.ts         # Recipe JSON → React Flow nodes/edges
    │   ├── useFlowToRecipe.ts         # React Flow nodes/edges → Recipe JSON
    │   └── useValidation.ts           # Real-time Zod validation
    ├── utils/
    │   ├── importRecipe.ts            # File API: read JSON files or ZIP
    │   ├── exportRecipe.ts            # File API: download JSON files or ZIP
    │   └── recipeDefaults.ts          # Default empty recipe templates
    ├── validation/
    │   └── schemas.ts                 # Re-export Zod schemas from node-runtime
    └── styles/
        ├── index.css                  # Global styles
        └── nodes.css                  # Node type colors and layout
```

## Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Toolbar                                                         │
│  [+ Goto] [+ Action] [+ Check] [+ Extract] [+ Wait]            │
│  ────── [New Recipe] [Import] [Export ZIP] [Validate] ──────    │
├────────┬────────────────────────────────────┬───────────────────┤
│ Files  │  Flow Canvas                        │ Properties       │
│        │                                     │                  │
│ v001/  │  ┌──────┐    ┌──────┐   ┌──────┐  │ Step: click_link │
│ ├ wf   │  │ goto │───►│click │──►│check │  │ op: act_cached   │
│ ├ act  │  │ .com │    │ link │   │ url  │  │                  │
│ ├ sel  │  └──────┘    └──────┘   └──────┘  │ targetKey:       │
│ ├ fp   │                                     │ [more_info.link ]│
│ └ pol  │                                     │                  │
│        │                                     │ onFail:          │
│ JSON ▼ │                                     │ [fallback     ▼] │
│ ┌────┐ │                                     │                  │
│ │edit│ │                                     │ Expects:         │
│ │area│ │                                     │ url_contains:    │
│ │    │ │                                     │ [iana.org       ]│
│ └────┘ │                                     │ [+ Add Expect]   │
├────────┴────────────────────────────────────┴───────────────────┤
│  Status: ✓ Valid  │  Steps: 3  │  Actions: 1  │  Selectors: 1  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. Flow Canvas (React Flow)
- Each workflow step = draggable node
- Nodes auto-connect in sequence (source→target edges)
- Drag from toolbar to add new step
- Delete node via keyboard (Del/Backspace) or context menu
- Minimap for large workflows
- Auto-layout on import

### 2. Custom Nodes (5 types, color-coded)
| Type | Color | Badge | Summary Fields |
|------|-------|-------|----------------|
| goto | #3B82F6 (blue) | 🔗 | url (truncated) |
| act_cached | #10B981 (green) | ▶ | targetKey |
| checkpoint | #F59E0B (amber) | ✓ | message |
| extract | #8B5CF6 (purple) | 📋 | scope or "page" |
| wait | #6B7280 (gray) | ⏱ | duration (ms) |

### 3. Property Panel
- Shows when a node is selected
- Form fields change based on node type
- `targetKey` field shows autocomplete from actions.json keys
- Expects editor: add/remove expectation rows
- Changes sync bidirectionally with JSON

### 4. File Tree + JSON Editor
- Left sidebar shows recipe file structure
- Click file to open in Monaco editor below
- Edits in Monaco update the flow canvas (and vice versa)
- Syntax highlighting + error markers from Zod validation

### 5. Import/Export
- **Import folder**: Select multiple JSON files → auto-detect which is which by content
- **Import ZIP**: Single ZIP containing 5 JSON files
- **Import single file**: Import individual JSON file to replace one part
- **Export ZIP**: Download all 5 files as recipe-{domain}-{version}.zip
- **Export individual**: Download any single JSON file
- All via browser File API (no server needed)

### 6. Validation
- Real-time Zod schema validation as user edits
- Red border on invalid nodes
- Status bar shows validation summary
- Cross-reference check: targetKeys in workflow must exist in actions.json
- Warning for missing selectors fallbacks

## State Management (Zustand)

```typescript
interface RecipeStore {
  // Recipe data
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  fingerprints: FingerprintsMap;
  policies: PoliciesMap;

  // Metadata
  domain: string;
  flow: string;
  version: string;
  isDirty: boolean;

  // Actions
  setWorkflow: (wf: Workflow) => void;
  addStep: (step: WorkflowStep) => void;
  updateStep: (id: string, patch: Partial<WorkflowStep>) => void;
  removeStep: (id: string) => void;
  reorderSteps: (from: number, to: number) => void;
  setActions: (actions: ActionsMap) => void;
  setSelectors: (selectors: SelectorsMap) => void;
  setFingerprints: (fp: FingerprintsMap) => void;
  setPolicies: (pol: PoliciesMap) => void;

  // Import/Export
  importRecipe: (files: Record<string, object>) => void;
  exportRecipe: () => Record<string, object>;
  resetToDefault: () => void;
}
```

## Dependencies

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@xyflow/react": "^12.0.0",
    "zustand": "^5.0.0",
    "@monaco-editor/react": "^4.7.0",
    "zod": "^3.24.0",
    "jszip": "^3.10.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "vitest": "^3.0.0",
    "@testing-library/react": "^16.0.0",
    "jsdom": "^25.0.0"
  }
}
```

## Team Structure

| Agent | Responsibility | Files |
|-------|---------------|-------|
| ui-core | Project scaffold, layout, store, import/export, validation | App.tsx, store/, hooks/, utils/, validation/ |
| ui-flow | React Flow canvas, custom nodes, property panel, toolbar | FlowCanvas.tsx, nodes/, PropertyPanel.tsx, Toolbar.tsx |

## Success Criteria

1. Can create a recipe from scratch via visual flow editor
2. Can import existing recipe files (individual or ZIP)
3. Can export recipe as ZIP or individual files
4. Real-time validation with Zod schemas
5. Property panel syncs bidirectionally with flow canvas
6. All 5 recipe file types editable (workflow via flow, others via Monaco/forms)
7. Responsive layout, works in modern browsers
