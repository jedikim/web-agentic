import { useCallback, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type OnSelectionChangeFunc,
  type OnNodesDelete,
  type Connection,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { nodeTypes, nodeColors } from '../nodes/nodeTypes.ts';
import { useRecipeToFlow } from '../hooks/useRecipeToFlow.ts';
import { useFlowToRecipe } from '../hooks/useFlowToRecipe.ts';
import { useRecipeStore } from '../store/recipeStore.ts';
import { useUiStore } from '../store/uiStore.ts';
import { useEffect } from 'react';
import type { WorkflowStep } from '../validation/schemas.ts';

function makeId(): string {
  return `step-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function createDefaultStep(op: string): WorkflowStep {
  const id = makeId();
  switch (op) {
    case 'goto':
      return { id, op: 'goto', args: { url: 'https://' } };
    case 'act_cached':
      return { id, op: 'act_cached', targetKey: '' };
    case 'checkpoint':
      return { id, op: 'checkpoint', args: { message: '' } };
    case 'extract':
      return { id, op: 'extract', args: { scope: '' } };
    case 'wait':
      return { id, op: 'wait', args: { ms: 1000 } };
    default:
      return { id, op: 'goto', args: {} };
  }
}

export function FlowCanvas() {
  const { nodes: recipeNodes, edges: recipeEdges } = useRecipeToFlow();
  const { syncNodeOrder } = useFlowToRecipe();
  const [nodes, setNodes, onNodesChange] = useNodesState(recipeNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(recipeEdges);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  const setSelectedNodeId = useUiStore((s) => s.setSelectedNodeId);
  const addStep = useRecipeStore((s) => s.addStep);
  const removeStep = useRecipeStore((s) => s.removeStep);

  // Sync recipe changes to flow nodes/edges
  useEffect(() => {
    setNodes(recipeNodes);
    setEdges(recipeEdges);
  }, [recipeNodes, recipeEdges, setNodes, setEdges]);

  const onSelectionChange: OnSelectionChangeFunc = useCallback(
    ({ nodes: selectedNodes }) => {
      if (selectedNodes.length === 1) {
        setSelectedNodeId(selectedNodes[0].id);
      } else {
        setSelectedNodeId(null);
      }
    },
    [setSelectedNodeId],
  );

  const onNodesDelete: OnNodesDelete = useCallback(
    (deleted) => {
      for (const node of deleted) {
        removeStep(node.id);
      }
    },
    [removeStep],
  );

  const onNodeDragStop = useCallback(() => {
    syncNodeOrder(nodes);
  }, [nodes, syncNodeOrder]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const op = e.dataTransfer.getData('application/reactflow-type');
      if (!op) return;

      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const step = createDefaultStep(op);

      // Place node at drop position temporarily; it'll snap to layout on next render
      void position;
      addStep(step);
    },
    [screenToFlowPosition, addStep],
  );

  // Suppress unused-variable lint for onConnect (we don't allow manual edge creation)
  const onConnect = useCallback((_connection: Connection) => {
    // Edges are auto-generated from step order; ignore manual connections
  }, []);

  return (
    <div className="canvas-area" ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        onNodesDelete={onNodesDelete}
        onNodeDragStop={onNodeDragStop}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        deleteKeyCode={['Backspace', 'Delete']}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls position="bottom-left" />
        <MiniMap
          position="bottom-right"
          nodeColor={(node) => nodeColors[node.type ?? ''] ?? '#666'}
          maskColor="rgba(0,0,0,0.5)"
        />
      </ReactFlow>
    </div>
  );
}
