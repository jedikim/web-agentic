import { z } from 'zod';

export const PolicyConditionSchema = z.object({
  field: z.string(),
  op: z.enum(['==', '!=', '<', '<=', '>', '>=', 'in', 'not_in', 'contains']),
  value: z.unknown(),
});

export const PolicyScoreRuleSchema = z.object({
  when: PolicyConditionSchema,
  add: z.number(),
});

export const PolicySchema = z.object({
  hard: z.array(PolicyConditionSchema),
  score: z.array(PolicyScoreRuleSchema),
  tie_break: z.array(z.string()),
  pick: z.enum(['argmax', 'argmin', 'first']),
});

export const PoliciesMapSchema = z.record(PolicySchema);
