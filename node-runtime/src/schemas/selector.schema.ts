import { z } from 'zod';

export const SelectorEntrySchema = z.object({
  primary: z.string(),
  fallbacks: z.array(z.string()),
  strategy: z.enum(['testid', 'role', 'css', 'xpath']),
});

export const SelectorsMapSchema = z.record(SelectorEntrySchema);
