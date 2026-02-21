import { z } from 'zod';

// --- Workflow ---

export const ExpectationSchema = z.object({
  kind: z.enum(['url_contains', 'selector_visible', 'text_contains', 'title_contains']),
  value: z.string(),
});

export const WorkflowStepSchema = z.object({
  id: z.string(),
  op: z.enum(['goto', 'act_cached', 'act_template', 'extract', 'choose', 'checkpoint', 'wait']),
  targetKey: z.string().nullable().optional(),
  args: z.record(z.string(), z.unknown()).nullable().optional(),
  expect: z.array(ExpectationSchema).nullable().optional(),
  onFail: z.enum(['retry', 'fallback', 'checkpoint', 'abort']).nullable().optional(),
});

export const WorkflowSchema = z.object({
  id: z.string(),
  version: z.string().nullable().optional(),
  vars: z.record(z.string(), z.unknown()).nullable().optional(),
  steps: z.array(WorkflowStepSchema).min(1),
});

// --- Actions ---

export const ActionRefSchema = z.object({
  selector: z.string(),
  description: z.string(),
  method: z.string(),
  arguments: z.array(z.string()).nullable().optional(),
});

export const ActionEntrySchema = z.object({
  instruction: z.string(),
  preferred: ActionRefSchema,
  observedAt: z.string(),
});

export const ActionsMapSchema = z.record(z.string(), ActionEntrySchema);

// --- Selectors ---

export const SelectorEntrySchema = z.object({
  primary: z.string(),
  fallbacks: z.array(z.string()),
  strategy: z.enum(['testid', 'role', 'css', 'xpath']),
});

export const SelectorsMapSchema = z.record(z.string(), SelectorEntrySchema);

// --- Fingerprints ---

export const FingerprintSchema = z.object({
  mustText: z.array(z.string()).nullable().optional(),
  mustSelectors: z.array(z.string()).nullable().optional(),
  urlContains: z.string().nullable().optional(),
});

export const FingerprintsMapSchema = z.record(z.string(), FingerprintSchema);

// --- Policies ---

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

export const PoliciesMapSchema = z.record(z.string(), PolicySchema);

// --- Types ---

export type Expectation = z.infer<typeof ExpectationSchema>;
export type WorkflowStep = z.infer<typeof WorkflowStepSchema>;
export type Workflow = z.infer<typeof WorkflowSchema>;
export type ActionRef = z.infer<typeof ActionRefSchema>;
export type ActionEntry = z.infer<typeof ActionEntrySchema>;
export type ActionsMap = z.infer<typeof ActionsMapSchema>;
export type SelectorEntry = z.infer<typeof SelectorEntrySchema>;
export type SelectorsMap = z.infer<typeof SelectorsMapSchema>;
export type Fingerprint = z.infer<typeof FingerprintSchema>;
export type FingerprintsMap = z.infer<typeof FingerprintsMapSchema>;
export type PolicyCondition = z.infer<typeof PolicyConditionSchema>;
export type PolicyScoreRule = z.infer<typeof PolicyScoreRuleSchema>;
export type Policy = z.infer<typeof PolicySchema>;
export type PoliciesMap = z.infer<typeof PoliciesMapSchema>;
