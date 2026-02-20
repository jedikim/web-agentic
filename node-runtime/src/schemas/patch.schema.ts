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
  key: z.string().nullable().optional(),
  step: z.string().nullable().optional(),
  value: z.unknown(),
});

export const PatchPayloadSchema = z.object({
  patch: z.array(PatchOpSchema),
  reason: z.string(),
});
