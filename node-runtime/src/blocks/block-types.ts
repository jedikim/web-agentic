import type { WorkflowStep } from '../types/index.js';

export interface BlockParameter {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'selector' | 'url';
  required: boolean;
  default?: unknown;
  description?: string;
}

export interface WorkflowBlock {
  id: string;
  type: 'navigation' | 'action' | 'extract' | 'validation';
  name: string;
  description: string;
  parameters: BlockParameter[];
  steps: WorkflowStep[];
}
