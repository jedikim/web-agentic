import { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { WorkflowStep } from '../validation/schemas.ts';

type WaitNodeData = { step: WorkflowStep; hasError: boolean };

export const WaitNode = memo(function WaitNode({ data, selected }: NodeProps<Node<WaitNodeData>>) {
  const step = data.step;
  const ms = (step.args as Record<string, unknown> | null | undefined)?.ms as number | undefined;

  return (
    <div className={`flow-node node-wait${selected ? ' selected' : ''}${data.hasError ? ' invalid' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-label">WAIT</div>
      <div className="node-detail">{ms != null ? `${ms}ms` : '(no duration)'}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
