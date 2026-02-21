import { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { WorkflowStep } from '../validation/schemas.ts';

type GotoNodeData = { step: WorkflowStep; hasError: boolean };

export const GotoNode = memo(function GotoNode({ data, selected }: NodeProps<Node<GotoNodeData>>) {
  const step = data.step;
  const url = (step.args as Record<string, unknown> | null | undefined)?.url as string | undefined;

  return (
    <div className={`flow-node node-goto${selected ? ' selected' : ''}${data.hasError ? ' invalid' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-label">GOTO</div>
      <div className="node-detail" title={url}>{url ?? '(no url)'}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
