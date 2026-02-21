import { ReactFlowProvider } from '@xyflow/react';
import { FileTree } from './components/FileTree.tsx';
import { JsonEditor } from './components/JsonEditor.tsx';
import { ValidationStatus } from './components/ValidationStatus.tsx';
import { Toolbar } from './components/Toolbar.tsx';
import { FlowCanvas } from './components/FlowCanvas.tsx';
import { PropertyPanel } from './components/PropertyPanel.tsx';
import './styles/index.css';
import './styles/nodes.css';

export default function App() {
  return (
    <ReactFlowProvider>
      <div className="app-layout">
        <Toolbar />

        <div className="main-content">
          <aside className="sidebar-left">
            <FileTree />
            <div className="json-editor-container">
              <JsonEditor />
            </div>
          </aside>

          <main className="canvas-area-wrapper">
            <FlowCanvas />
          </main>

          <aside className="sidebar-right">
            <PropertyPanel />
          </aside>
        </div>

        <footer className="status-bar">
          <ValidationStatus />
        </footer>
      </div>
    </ReactFlowProvider>
  );
}
