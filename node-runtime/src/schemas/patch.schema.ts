import { z } from 'zod';

export const PatchOpSchema = z.object({
  op: z.enum([
    'actions.replace',
    'actions.add',
    'selectors.add',
    'selectors.replace',
    'workflow.update_expect',
    'policies.update',
  ]),
  key: z.string().optional(),
  step: z.string().optional(),
  value: z.unknown(),
});

export const PatchPayloadSchema = z.object({
  patch: z.array(PatchOpSchema),
  reason: z.string(),
});
