import { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { WorkflowStep } from '../validation/schemas.ts';

type CheckpointNodeData = { step: WorkflowStep; hasError: boolean; runStatus?: string };

export const CheckpointNode = memo(function CheckpointNode({ data, selected }: NodeProps<Node<CheckpointNodeData>>) {
  const step = data.step;
  const message = (step.args as Record<string, unknown> | null | undefined)?.message as string | undefined;
  const runCls = data.runStatus ? ` run-${data.runStatus}` : '';

  return (
    <div className={`flow-node node-checkpoint${selected ? ' selected' : ''}${data.hasError ? ' invalid' : ''}${runCls}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-label">CHECK</div>
      <div className="node-detail" title={message}>{message ?? '(no message)'}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
