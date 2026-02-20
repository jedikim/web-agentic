import { z } from 'zod';

export const ActionRefSchema = z.object({
  selector: z.string(),
  description: z.string(),
  method: z.string(),
  arguments: z.array(z.string()).optional(),
});

export const ActionEntrySchema = z.object({
  instruction: z.string(),
  preferred: ActionRefSchema,
  observedAt: z.string(),
});

export const ActionsMapSchema = z.record(ActionEntrySchema);
