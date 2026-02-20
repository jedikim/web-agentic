export type PatchOpType =
  | 'actions.replace'
  | 'actions.add'
  | 'selectors.add'
  | 'selectors.replace'
  | 'workflow.update_expect'
  | 'policies.update';

export interface PatchOp {
  op: PatchOpType;
  key?: string;
  step?: string;
  value: unknown;
}

export interface PatchPayload {
  patch: PatchOp[];
  reason: string;
}
