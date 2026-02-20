import { z } from 'zod';

export const FingerprintSchema = z.object({
  mustText: z.array(z.string()).nullable().optional(),
  mustSelectors: z.array(z.string()).nullable().optional(),
  urlContains: z.string().nullable().optional(),
});

export const FingerprintsMapSchema = z.record(FingerprintSchema);
