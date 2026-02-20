import { z } from 'zod';

export const FingerprintSchema = z.object({
  mustText: z.array(z.string()).optional(),
  mustSelectors: z.array(z.string()).optional(),
  urlContains: z.string().optional(),
});

export const FingerprintsMapSchema = z.record(FingerprintSchema);
