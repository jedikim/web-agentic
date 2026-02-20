import { z } from 'zod';

export const ExpectationSchema = z.object({
  kind: z.enum(['url_contains', 'selector_visible', 'text_contains', 'title_contains']),
  value: z.string(),
});

export const WorkflowStepSchema = z.object({
  id: z.string(),
  op: z.enum(['goto', 'act_cached', 'act_template', 'extract', 'choose', 'checkpoint', 'wait']),
  targetKey: z.string().optional(),
  args: z.record(z.unknown()).optional(),
  expect: z.array(ExpectationSchema).optional(),
  onFail: z.enum(['retry', 'fallback', 'checkpoint', 'abort']).optional(),
});

export const WorkflowSchema = z.object({
  id: z.string(),
  version: z.string().optional(),
  vars: z.record(z.unknown()).optional(),
  steps: z.array(WorkflowStepSchema).min(1),
});
