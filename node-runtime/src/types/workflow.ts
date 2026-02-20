export interface Expectation {
  kind: 'url_contains' | 'selector_visible' | 'text_contains' | 'title_contains';
  value: string;
}

export interface WorkflowStep {
  id: string;
  op: 'goto' | 'act_cached' | 'act_template' | 'extract' | 'choose' | 'checkpoint' | 'wait';
  targetKey?: string;
  args?: Record<string, unknown>;
  expect?: Expectation[];
  onFail?: 'retry' | 'fallback' | 'checkpoint' | 'abort';
}

export interface Workflow {
  id: string;
  version?: string;
  vars?: Record<string, unknown>;
  steps: WorkflowStep[];
}
