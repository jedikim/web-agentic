import { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { WorkflowStep } from '../validation/schemas.ts';

type ExtractNodeData = { step: WorkflowStep; hasError: boolean; runStatus?: string };

export const ExtractNode = memo(function ExtractNode({ data, selected }: NodeProps<Node<ExtractNodeData>>) {
  const step = data.step;
  const scope = (step.args as Record<string, unknown> | null | undefined)?.scope as string | undefined;
  const runCls = data.runStatus ? ` run-${data.runStatus}` : '';

  return (
    <div className={`flow-node node-extract${selected ? ' selected' : ''}${data.hasError ? ' invalid' : ''}${runCls}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-label">EXTRACT</div>
      <div className="node-detail" title={scope}>{scope ?? 'full page'}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
