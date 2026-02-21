import { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { WorkflowStep } from '../validation/schemas.ts';

type ActCachedNodeData = { step: WorkflowStep; hasError: boolean; runStatus?: string };

export const ActCachedNode = memo(function ActCachedNode({ data, selected }: NodeProps<Node<ActCachedNodeData>>) {
  const step = data.step;
  const runCls = data.runStatus ? ` run-${data.runStatus}` : '';

  return (
    <div className={`flow-node node-act${selected ? ' selected' : ''}${data.hasError ? ' invalid' : ''}${runCls}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-label">ACTION</div>
      <div className="node-detail" title={step.targetKey ?? undefined}>{step.targetKey ?? '(no target)'}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
