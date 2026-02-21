import type { NodeTypes } from '@xyflow/react';
import { GotoNode } from './GotoNode.tsx';
import { ActCachedNode } from './ActCachedNode.tsx';
import { CheckpointNode } from './CheckpointNode.tsx';
import { ExtractNode } from './ExtractNode.tsx';
import { WaitNode } from './WaitNode.tsx';

export const nodeTypes: NodeTypes = {
  goto: GotoNode,
  act_cached: ActCachedNode,
  checkpoint: CheckpointNode,
  extract: ExtractNode,
  wait: WaitNode,
};

export const nodeColors: Record<string, string> = {
  goto: '#3B82F6',
  act_cached: '#10B981',
  checkpoint: '#F59E0B',
  extract: '#8B5CF6',
  wait: '#6B7280',
};

export const nodeLabels: Record<string, string> = {
  goto: 'GOTO',
  act_cached: 'ACTION',
  checkpoint: 'CHECK',
  extract: 'EXTRACT',
  wait: 'WAIT',
};
